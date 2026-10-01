param(
    [Parameter(Mandatory=$true)][string]$RunDirectory,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId,
    [Parameter(Mandatory=$true)][string]$SessionRoot,
    [ValidateSet('Draw','Recover')][string]$Mode='Draw',
    [ValidateRange(10,900)][int]$TimeoutSeconds=240
)
# Private desktop adapter. Never operate in an existing user drawing or quit AutoCAD.
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$runPath=(Resolve-Path -LiteralPath $RunDirectory).Path
$repoPath=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$outputPath=Join-Path $runPath 'floor.dwg'
$marker=Join-Path $runPath 'command.finished'
$receiptPath=Join-Path $runPath 'cad_receipt.json'
$sessionPath=Join-Path $SessionRoot ($RunId+'.json')
$cancelPath=Join-Path $runPath 'cancel.request'
$clock=[Diagnostics.Stopwatch]::StartNew()
$cadApp=$null; $cadDoc=$null; $locked=$false; $filter=$false
$code='cad_failed'
$report=@{state='FAILED';run_id=$RunId;reopened=$false;scene_verified=$false}
$session=@{}
$sessionData=Get-Content -LiteralPath $sessionPath -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($property in $sessionData.PSObject.Properties) {$session[$property.Name]=$property.Value}
if ($session.schema -ne 1 -or $session.run_id -cne $RunId -or $session.run_directory -cne $runPath) {throw 'Invalid CAD session identity'}
if ($Mode -eq 'Draw') {
    $session.bridge_pid=$PID
    $session.bridge_start=(Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks
} else {$session.recovery_pid=$PID}
$mutex=New-Object System.Threading.Mutex($false,'Local\StructAgent.AutoCAD.Desktop')
function Write-AtomicJson([string]$path,$data) {
    $temp=$path+'.'+[guid]::NewGuid().ToString('N')+'.tmp'
    try {
        $bytes=[Text.Encoding]::UTF8.GetBytes(($data | ConvertTo-Json -Depth 12))
        $stream=New-Object IO.FileStream($temp,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        try {$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)} finally {$stream.Dispose()}
        # PowerShell 5.1 casts $null to an empty string for this overload.
        if ([IO.File]::Exists($path)) {[IO.File]::Replace($temp,$path,[NullString]::Value)} else {[IO.File]::Move($temp,$path)}
    } finally {if ([IO.File]::Exists($temp)) {[IO.File]::Delete($temp)}}
}
function Write-Session { Write-AtomicJson $sessionPath $session }
function Owns-Document($document) {
    try {
        $value=''
        $document.SummaryInfo.GetCustomByKey('StructAgent.RunId',[ref]$value)
        return $value -ceq $RunId -and ($document.Name -ceq $session.created_document -or
            $document.FullName -ceq $session.owned_path -or $document.FullName -ceq $outputPath)
    } catch {return $false}
}
function Deadline {
    if ($clock.Elapsed.TotalSeconds -gt $TimeoutSeconds) { $script:code='cad_timeout'; throw 'CAD operation exceeded its time limit.' }
    if ($Mode -eq 'Draw' -and (Test-Path -LiteralPath $cancelPath)) {$script:code='cad_cancelled';throw 'CAD operation cancelled by its owner.'}
}
function LispPath([string]$value) {
    if ($value.Contains("`n") -or $value.Contains("`r")) {throw 'Invalid newline in path'}
    return '"'+$value.Replace('\','/').Replace('"','\"')+'"'
}
function Near($actual,$expected,[double]$tolerance=0.01) {
    if ([double]::IsNaN([double]$actual) -or [double]::IsInfinity([double]$actual) -or
        [math]::Abs([double]$actual-[double]$expected) -gt $tolerance) {
        throw ('Drawing measurement mismatch: '+$actual+' expected '+$expected)
    }
}
function Point($actual,$expected,$offset) {
    Near $actual[0] ([double]$expected[0]+$offset[0])
    Near $actual[1] ([double]$expected[1]+$offset[1])
    Near $actual[2] 0
}
function Verify-Scene($doc,$scene) {
    $index=0; $texts=0; $dimensions=0
    $expectedCount=0
    foreach ($group in $scene.groups.PSObject.Properties) {$expectedCount+=$group.Value.Count}
    if ($doc.ModelSpace.Count -ne $expectedCount) {
        throw ('CAD created '+$doc.ModelSpace.Count+' entities; expected '+$expectedCount+'. Drawing may have failed or been cancelled.')
    }
    $types=@{LINE='AcDbLine';POLY='AcDbPolyline';ARC='AcDbArc';CIRCLE='AcDbCircle';TEXT='AcDbText';DIM='AcDbRotatedDimension'}
    foreach ($group in @('PLAN','BEAMS','DETAIL','ENVELOPE','TABLE','SLAB','DIMENSIONS','COEFF')) {
        $offset=$scene.offsets.$group
        foreach ($item in $scene.groups.$group) {
            Deadline
            $entity=$doc.ModelSpace.Item($index); $index++
            $kind=[string]$item[0]
            if ($entity.ObjectName -cne $types[$kind]) {throw ('Entity type mismatch at '+$index)}
            $layer=[string]$entity.Layer
            if ($layer -cne ('RF-'+$item[1]) -and -not $layer.StartsWith('RF-'+$item[1]+'-')) {throw 'Entity layer mismatch'}
            switch ($kind) {
                LINE { Point $entity.StartPoint $item[2] $offset; Point $entity.EndPoint $item[3] $offset }
                CIRCLE { Point $entity.Center $item[2] $offset; Near $entity.Radius $item[3] }
                ARC {
                    Point $entity.Center $item[2] $offset; Near $entity.Radius $item[3]
                    Near $entity.ArcLength ([double]$item[3]*[double]$item[5]*[math]::PI/180)
                    Near ([math]::Cos($entity.StartAngle)) ([math]::Cos([double]$item[4]*[math]::PI/180)) 0.000001
                    Near ([math]::Sin($entity.StartAngle)) ([math]::Sin([double]$item[4]*[math]::PI/180)) 0.000001
                }
                POLY {
                    $coords=$entity.Coordinates
                    if ($coords.Count -ne 2*$item[3].Count -or $entity.Closed -ne [bool]$item[2]) {throw 'Polyline structure mismatch'}
                    for ($j=0;$j -lt $item[3].Count;$j++) {
                        Near $coords[2*$j] ([double]$item[3][$j][0]+$offset[0])
                        Near $coords[2*$j+1] ([double]$item[3][$j][1]+$offset[1])
                        Near ($entity.GetBulge($j)) 0
                    }
                }
                TEXT {
                    $texts++
                    if ([string]$entity.TextString -cne [string]$item[5]) {throw ('Unicode text mismatch at '+$index)}
                    if ($entity.StyleName -cne 'RF-TEXT') {throw 'Text style mismatch'}
                    Point $entity.InsertionPoint $item[2] $offset
                    Near $entity.Height $item[3]
                    Near $entity.Rotation ([double]$item[4]*[math]::PI/180) 0.000001
                }
                DIM {
                    $dimensions++
                    $angle=[double]$item[5]*[math]::PI/180
                    $expected=[math]::Abs(([double]$item[3][0]-$item[2][0])*[math]::Cos($angle)+([double]$item[3][1]-$item[2][1])*[math]::Sin($angle))
                    $factor=1.0; if ($item.Count -gt 6) {$factor=[double]$item[6]}
                    # ActiveX Measurement already includes DIMLFAC in this backend.
                    Near $entity.Measurement ($expected*$factor)
                    Near $entity.LinearScaleFactor $factor 0.00000001
                    if ($entity.TextOverride -ne '') {throw 'Unexpected dimension text override'}
                }
            }
        }
    }
    if ($doc.ModelSpace.Count -ne $index) {throw 'Model space entity count mismatch'}
    $style=$doc.TextStyles.Item('RF-TEXT')
    if ($style.BigFontFile -ne '' -or [IO.Path]::GetFileName($style.FontFile) -notin @('simhei.ttf','simsun.ttc','msyh.ttc')) {throw 'Chinese font mismatch'}
    foreach ($key in @('CENTER','HIDDEN','ERECT')) {
        $found=$false
        foreach ($layer in $doc.Layers) {
            if ($layer.Name -eq ('RF-'+$key) -or $layer.Name.StartsWith('RF-'+$key+'-')) {
                $found=$true
                if ($layer.Linetype -ne ('RF-'+$key)) {throw 'Line type mismatch'}
            }
        }
        if (-not $found) {throw 'Required layer missing'}
    }
    return @{entities=$index;texts=$texts;dimensions=$dimensions}
}
try {
    if ($Mode -eq 'Recover' -and $session.bridge_pid -and $session.bridge_start) {
        $orphan=Get-Process -Id $session.bridge_pid -ErrorAction SilentlyContinue
        if ($null -ne $orphan -and $orphan.StartTime.ToUniversalTime().Ticks -eq $session.bridge_start) {
            $owner=Get-Process -Id $session.owner_pid -ErrorAction SilentlyContinue
            if ($session.state -ne 'RECOVERY_REQUIRED' -and $null -ne $owner -and
                $owner.StartTime.ToUniversalTime().ToFileTimeUtc().ToString() -eq $session.owner_identity) {
                $code='cad_busy';throw 'Original execution owner is still active.'
            }
            $code='cad_recovery_required'
            try {$processInfo=Get-CimInstance Win32_Process -Filter ('ProcessId='+$session.bridge_pid) -ErrorAction Stop}
            catch {throw ('Cannot verify bridge process ownership: '+$_.Exception.Message)}
            if ($null -eq $processInfo -or [string]::IsNullOrEmpty($processInfo.CommandLine)) {
                throw 'Bridge process ownership metadata is unavailable.'
            }
            if ($orphan.ProcessName -ne 'powershell' -or -not $processInfo.CommandLine.Contains($PSCommandPath) -or
                -not $processInfo.CommandLine.Contains($RunId) -or -not $processInfo.CommandLine.Contains($runPath)) {
                $code='cad_recovery_required';throw 'Bridge process ownership cannot be verified.'
            }
            # Only the recorded helper incarnation is stopped. Never stop AutoCAD.
            Stop-Process -Id $session.bridge_pid -ErrorAction Stop
            $orphan.WaitForExit(1000) | Out-Null
        }
    }
    try {$locked=$mutex.WaitOne(0)} catch [System.Threading.AbandonedMutexException] {$locked=$true}
    if (-not $locked) {$code='cad_busy';throw 'Another StructAgent CAD operation is active.'}
    if ($Mode -eq 'Draw') {
        foreach ($file in @($outputPath,$marker,$receiptPath)) {
            if (Test-Path -LiteralPath $file) {throw 'Refusing to reuse CAD output or receipt.'}
        }
    }
    Add-Type -Path (Join-Path $PSScriptRoot 'cad_message_filter.cs')
    [SALifecycleFilter]::Register($TimeoutSeconds);$filter=$true
    try {$cadApp=[Runtime.InteropServices.Marshal]::GetActiveObject('AutoCAD.Application.24.1')}
    catch {
        if ($Mode -eq 'Recover') {
            if ($session.app_pid) {
                $oldProcess=Get-Process -Id $session.app_pid -ErrorAction SilentlyContinue
                if ($null -ne $oldProcess -and $oldProcess.StartTime.ToUniversalTime().Ticks -eq $session.app_start) {
                    $code='cad_recovery_required';throw 'The original CAD process exists but cannot be reached.'
                }
            }
            $session.state='CLOSED';$session.recovery='Original CAD session no longer exists.';Write-Session
            $report.state='RECOVERED'
            return
        }
        $code='cad_unavailable';throw 'Open AutoCAD 2022 and finish its startup dialogs before retrying.'
    }
    if (-not $cadApp.Version.StartsWith('24.1')) {$code='cad_unavailable';throw 'AutoCAD 2022 is required.'}
    $appPid=[SALifecycleFilter]::ProcessId($cadApp.HWND)
    $appStart=(Get-Process -Id $appPid).StartTime.ToUniversalTime().Ticks
    if ($Mode -eq 'Recover') {
        if ($session.app_pid -and ($appPid -ne $session.app_pid -or $appStart -ne $session.app_start)) {
            $session.state='CLOSED';$session.recovery='The original CAD process exited; current instance is untouched.';Write-Session
            $report.state='RECOVERED'
            return
        }
        if (-not $session.creation_attempted) {
            $session.state='CLOSED';Write-Session;$report.state='RECOVERED'
            return
        }
        # Cancellation is cooperative; never send Esc to a user command.
        [IO.File]::WriteAllText($cancelPath,$RunId)
        while (-not $cadApp.GetAcadState().IsQuiescent) {Deadline;Start-Sleep -Milliseconds 100}
        $ambiguous=$false
        foreach ($candidate in $cadApp.Documents) {
            if (Owns-Document $candidate) {$cadDoc=$candidate;break}
            if ($candidate.Name -ceq $session.created_document -or $candidate.FullName -ceq $session.owned_path) {$ambiguous=$true}
        }
        if ($null -eq $cadDoc) {
            if ($ambiguous) {$code='cad_recovery_required';throw 'Recorded document exists but its ownership marker differs; it is left untouched.'}
            if (-not $session.created_document) {$code='cad_recovery_required';throw 'Document ownership was not recorded; inspect the original CAD session.'}
            $session.state='CLOSED';$session.recovery='Owned document was already closed.';Write-Session
        } else {
            if ($cadDoc.GetVariable('CMDACTIVE') -ne 0) {$code='cad_recovery_required';throw 'Owned drawing is still running a command.'}
            $report.entities_before_close=$cadDoc.ModelSpace.Count
            $report.final_variables=@{}
            foreach ($key in @('CMDECHO','CLAYER','OSMODE','INSUNITS','UNDOCTL')) {$report.final_variables[$key]=$cadDoc.GetVariable($key)}
            $cadDoc.Close($false);$cadDoc=$null
            $session.state='CLOSED';$session.recovery='Cancelled and closed the owned document.';Write-Session
        }
        $report.state='RECOVERED'
        return
    }
    if (-not $cadApp.GetAcadState().IsQuiescent) {$code='cad_busy';throw 'AutoCAD is busy; finish the current command before retrying.'}
    $report.original_documents=@($cadApp.Documents | ForEach-Object {$_.Name})
    $scene=Get-Content -LiteralPath (Join-Path $runPath 'drawing_scene.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($scene.version -ne 'RCFLOOR-SCENE-2') {throw 'Unsupported CAD scene version'}
    Deadline
    $session.app_pid=$appPid;$session.app_start=$appStart;$session.creation_attempted=$true
    $session.state='ACTIVE';Write-Session
    $cadDoc=$cadApp.Documents.Add()
    $report.created_document=$cadDoc.Name
    $cadDoc.SummaryInfo.AddCustomInfo('StructAgent.RunId',$RunId)
    $session.created_document=$cadDoc.Name
    $session.owned_path=Join-Path $runPath 'session.dwg'
    Write-Session
    $cadDoc.SaveAs($session.owned_path,64)
    $session.created_document=$cadDoc.Name;Write-Session
    $cadDoc.SetVariable('INSUNITS',4);$cadDoc.SetVariable('TILEMODE',1)
    $cadDoc.Activate()
    if ($cadDoc.ModelSpace.Count -ne 0) {throw 'New CAD document is not empty'}
    if ($cadDoc.GetVariable('LISPSYS') -eq 0) {$code='cad_unicode_required';throw 'Enable the Unicode AutoLISP engine and restart AutoCAD before retrying.'}
    $before=@{};foreach ($key in @('CMDECHO','CLAYER','OSMODE','INSUNITS','UNDOCTL')) {$before[$key]=$cadDoc.GetVariable($key)}
    $report.before=$before
    # Load the previously approved source path, not a per-run copy requiring fresh trust.
    $load='(progn (setq sa:loaded nil) (load '+(LispPath (Join-Path $repoPath 'legacy/rc_floor/RCFLOOR.lsp'))+') (rf:read '+(LispPath (Join-Path $runPath 'floor_data.dat'))+') (setq *rf:cancel-file* '+(LispPath $cancelPath)+' sa:loaded "'+$RunId+'") (princ))'
    $finish='(progn (setq *rf:cancel-file* nil sa:fh (open '+(LispPath $marker)+' "w")) (write-line (if (= sa:loaded "'+$RunId+'") "'+$RunId+'" "FAILED") sa:fh) (close sa:fh) (setq sa:fh nil) (princ))'
    $session.phase='DRAWING';Write-Session
    $cadDoc.SendCommand($load+"`nRFALL`n_non`n0,0,0`n"+$finish+"`n")
    while (-not (Test-Path -LiteralPath $marker)) {Deadline;Start-Sleep -Milliseconds 200}
    while (-not $cadApp.GetAcadState().IsQuiescent -or $cadDoc.GetVariable('CMDACTIVE') -ne 0) {Deadline;Start-Sleep -Milliseconds 200}
    Deadline
    if ((Get-Content -LiteralPath $marker -Raw).Trim() -cne $RunId) {throw 'CAD command completion token mismatch'}
    $after=@{};foreach ($key in $before.Keys) {$after[$key]=$cadDoc.GetVariable($key)}
    foreach ($key in @('CMDECHO','CLAYER','OSMODE','INSUNITS')) {
        if ($before[$key] -ne $after[$key]) {throw ('System variable not restored: '+$key)}
    }
    if (($before.UNDOCTL -band 8) -ne ($after.UNDOCTL -band 8)) {throw 'Undo group was not restored'}
    $session.phase='VERIFYING';Write-Session
    $code='cad_verification_failed'
    $null=Verify-Scene $cadDoc $scene
    Deadline
    $cadDoc.Regen(1);$cadApp.ZoomExtents()
    $cadDoc.SaveAs($outputPath,64)
    $session.owned_path=$outputPath;Write-Session
    $cadDoc.Close($false);$cadDoc=$null
    Deadline
    $session.phase='REOPENING';Write-Session
    $cadDoc=$cadApp.Documents.Open($outputPath,$true)
    $check=Verify-Scene $cadDoc $scene
    $report.state='SUCCESS';$report.reopened=$true;$report.scene_verified=$true
    $report.entities=$check.entities;$report.texts=$check.texts;$report.dimensions=$check.dimensions
    $report.before=$before;$report.after=$after;$report.autocad_version=$cadApp.Version
} catch {
    $report.code=$code;$report.message=$_.Exception.Message
    Write-Output $_.ScriptStackTrace
    Write-Output $_.Exception.ToString()
} finally {
    if ($null -ne $cadDoc) {
        try {
            if ($cadApp.GetAcadState().IsQuiescent -and $cadDoc.GetVariable('CMDACTIVE') -eq 0) {
                $report.after=@{}
                foreach ($key in @('CMDECHO','CLAYER','OSMODE','INSUNITS','UNDOCTL')) {$report.after[$key]=$cadDoc.GetVariable($key)}
                if (Owns-Document $cadDoc) {$cadDoc.Close($false);$report.owned_document_closed=$true}
                else {$report.owned_document_closed=$false}
            } else {$report.owned_document_closed=$false}
        } catch {$report.owned_document_closed=$false;$report.cleanup_warning=$_.Exception.Message}
    }
    if ($Mode -eq 'Draw') {
        $session.state=if ($report.owned_document_closed -eq $true -or -not $session.creation_attempted) {'CLOSED'} else {'RECOVERY_REQUIRED'}
        Write-Session
    }
    $report.elapsed_seconds=$clock.Elapsed.TotalSeconds
    Write-AtomicJson $(if ($Mode -eq 'Draw') {$receiptPath} else {Join-Path $runPath 'recovery_receipt.json'}) $report
    if ($filter) {[SALifecycleFilter]::Revoke()}
    if ($locked) {$mutex.ReleaseMutex()}
    $mutex.Dispose()
}
if ($report.state -ne 'SUCCESS') {exit 1}
