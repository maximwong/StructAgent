param(
    [Parameter(Mandatory=$true)][string]$RunDirectory,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$RunId,
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
$clock=[Diagnostics.Stopwatch]::StartNew()
$cadApp=$null; $cadDoc=$null; $locked=$false; $filter=$false
$code='cad_failed'
$report=@{state='FAILED';run_id=$RunId;reopened=$false;scene_verified=$false}
$mutex=New-Object System.Threading.Mutex($false,'Local\StructAgent.AutoCAD.Desktop')
function Deadline {
    if ($clock.Elapsed.TotalSeconds -gt $TimeoutSeconds) { $script:code='cad_timeout'; throw 'CAD operation exceeded its time limit.' }
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
    try {$locked=$mutex.WaitOne(0)} catch [System.Threading.AbandonedMutexException] {$locked=$true}
    if (-not $locked) {$code='cad_busy';throw 'Another StructAgent CAD operation is active.'}
    foreach ($file in @($outputPath,$marker,$receiptPath)) {
        if (Test-Path -LiteralPath $file) {throw 'Refusing to reuse CAD output or receipt.'}
    }
    Add-Type -Path (Join-Path $repoPath 'legacy/rc_floor/com_filter.cs')
    [CadMessageFilter]::Register();$filter=$true
    try {$cadApp=[Runtime.InteropServices.Marshal]::GetActiveObject('AutoCAD.Application.24.1')}
    catch {$code='cad_unavailable';throw 'Open AutoCAD 2022 and finish its startup dialogs before retrying.'}
    if (-not $cadApp.Version.StartsWith('24.1')) {$code='cad_unavailable';throw 'AutoCAD 2022 is required.'}
    if (-not $cadApp.GetAcadState().IsQuiescent) {$code='cad_busy';throw 'AutoCAD is busy; finish the current command before retrying.'}
    $report.original_documents=@($cadApp.Documents | ForEach-Object {$_.Name})
    $scene=Get-Content -LiteralPath (Join-Path $runPath 'drawing_scene.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($scene.version -ne 'RCFLOOR-SCENE-2') {throw 'Unsupported CAD scene version'}
    Deadline
    $cadDoc=$cadApp.Documents.Add()
    $report.created_document=$cadDoc.Name
    $cadDoc.SetVariable('INSUNITS',4);$cadDoc.SetVariable('TILEMODE',1)
    $cadDoc.Activate()
    if ($cadDoc.ModelSpace.Count -ne 0) {throw 'New CAD document is not empty'}
    if ($cadDoc.GetVariable('LISPSYS') -eq 0) {$code='cad_unicode_required';throw 'Enable the Unicode AutoLISP engine and restart AutoCAD before retrying.'}
    $before=@{};foreach ($key in @('CMDECHO','CLAYER','OSMODE','INSUNITS','UNDOCTL')) {$before[$key]=$cadDoc.GetVariable($key)}
    # Load the previously approved source path, not a per-run copy requiring fresh trust.
    $load='(progn (setq sa:loaded nil) (load '+(LispPath (Join-Path $repoPath 'legacy/rc_floor/RCFLOOR.lsp'))+') (rf:read '+(LispPath (Join-Path $runPath 'floor_data.dat'))+') (setq sa:loaded "'+$RunId+'") (princ))'
    $finish='(progn (setq sa:fh (open '+(LispPath $marker)+' "w")) (write-line (if (= sa:loaded "'+$RunId+'") "'+$RunId+'" "FAILED") sa:fh) (close sa:fh) (setq sa:fh nil) (princ))'
    $cadDoc.SendCommand($load+"`nRFALL`n_non`n0,0,0`n"+$finish+"`n")
    while (-not (Test-Path -LiteralPath $marker)) {Deadline;Start-Sleep -Milliseconds 200}
    while (-not $cadApp.GetAcadState().IsQuiescent -or $cadDoc.GetVariable('CMDACTIVE') -ne 0) {Deadline;Start-Sleep -Milliseconds 200}
    if ((Get-Content -LiteralPath $marker -Raw).Trim() -cne $RunId) {throw 'CAD command completion token mismatch'}
    $after=@{};foreach ($key in $before.Keys) {$after[$key]=$cadDoc.GetVariable($key)}
    foreach ($key in @('CMDECHO','CLAYER','OSMODE','INSUNITS')) {
        if ($before[$key] -ne $after[$key]) {throw ('System variable not restored: '+$key)}
    }
    if (($before.UNDOCTL -band 8) -ne ($after.UNDOCTL -band 8)) {throw 'Undo group was not restored'}
    $code='cad_verification_failed'
    $null=Verify-Scene $cadDoc $scene
    Deadline
    $cadDoc.Regen(1);$cadApp.ZoomExtents()
    $cadDoc.SaveAs($outputPath,64)
    $cadDoc.Close($false);$cadDoc=$null
    Deadline
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
                $cadDoc.Close($false);$report.owned_document_closed=$true
            } else {$report.owned_document_closed=$false}
        } catch {$report.owned_document_closed=$false;$report.cleanup_warning=$_.Exception.Message}
    }
    $report.elapsed_seconds=$clock.Elapsed.TotalSeconds
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
    if ($filter) {[CadMessageFilter]::Revoke()}
    if ($locked) {$mutex.ReleaseMutex()}
    $mutex.Dispose()
}
if ($report.state -ne 'SUCCESS') {exit 1}
