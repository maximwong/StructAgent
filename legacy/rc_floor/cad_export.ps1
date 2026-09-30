param([Parameter(Mandatory=$true)][string]$Scene,[Parameter(Mandatory=$true)][string]$OutputDwg,[switch]$CapturePreview,[switch]$NewInstance)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
Add-Type -Path (Join-Path $PSScriptRoot 'com_filter.cs')
[CadMessageFilter]::Register()
$cadApp=$null;$cadDoc=$null;$ownApp=$false
function Point3($xy,$off) { return ,([double[]]@(([double]$xy[0]+$off[0]),([double]$xy[1]+$off[1]),0.0)) }
function Write-Stage($message) { Write-Output $message }
try {
    $sceneData=Get-Content -LiteralPath $Scene -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($sceneData.version -ne 'RCFLOOR-SCENE-2') { throw 'Unsupported scene version' }
    if (Test-Path -LiteralPath $OutputDwg) { throw 'Output DWG already exists; choose a new output filename.' }
    Write-Stage 'Connecting to AutoCAD 2022'
    if ($NewInstance) {
        $priorHandle=$null
        try {$priorHandle=[Runtime.InteropServices.Marshal]::GetActiveObject('AutoCAD.Application.24.1').HWND} catch {}
        $cadApp=New-Object -ComObject AutoCAD.Application.24.1
        $ownApp=($null -eq $priorHandle -or $cadApp.HWND -ne $priorHandle)
        $cadApp.Visible=$true
    } else {
        try { $cadApp=[Runtime.InteropServices.Marshal]::GetActiveObject('AutoCAD.Application.24.1') }
        catch { $cadApp=New-Object -ComObject AutoCAD.Application.24.1; $ownApp=$true; $cadApp.Visible=$true }
    }
    if (-not $cadApp.Version.StartsWith('24.1')) { throw 'AutoCAD 2022 required' }
    Write-Stage 'Creating a new document'
        try {$cadDoc=$cadApp.Documents.Add()} catch {
        $template=Get-ChildItem -LiteralPath (Join-Path $env:LOCALAPPDATA 'Autodesk/AutoCAD 2022/R24.1') -Filter acadiso.dwt -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $template) {throw}
        Write-Stage 'Retrying with installed acadiso.dwt template'
        try {$cadDoc=$cadApp.Documents.Add($template.FullName)} catch {
            # Keep all existing documents; retry only in a separately owned instance.
            $failedHandle=$cadApp.HWND
            Write-Stage 'Existing instance cannot create documents; trying a separate AutoCAD instance'
            $fresh=New-Object -ComObject AutoCAD.Application.24.1
            if ($fresh.HWND -eq $failedHandle) {throw 'AutoCAD returned the same blocked instance; close its dialog and retry.'}
            $cadApp=$fresh;$ownApp=$true;$cadApp.Visible=$true
            $cadDoc=$cadApp.Documents.Add($template.FullName)
        }
    }
    $ready=[DateTime]::UtcNow.AddSeconds(30)
    while (-not $cadApp.GetAcadState().IsQuiescent) {if ([DateTime]::UtcNow -gt $ready) {throw "AutoCAD document not ready"};Start-Sleep -Milliseconds 200}
    $cadDoc.SetVariable('INSUNITS',4);$cadDoc.SetVariable('LUNITS',2);$cadDoc.SetVariable('MEASUREMENT',1)
    $space=$cadDoc.ModelSpace
    $fontPath=Join-Path $env:WINDIR 'Fonts/simhei.ttf';$face=[string][char]0x9ED1+[char]0x4F53;$pitch=38
    if (-not (Test-Path -LiteralPath $fontPath)) { $fontPath=Join-Path $env:WINDIR 'Fonts/simsun.ttc';$face=[string][char]0x5B8B+[char]0x4F53;$pitch=22 }
    if (-not (Test-Path -LiteralPath $fontPath)) { throw 'Chinese font not found' }
    # A unique new style has no Big Font. Never write BigFontFile="" via ActiveX.
    $styleName='RF-TEXT'
    try { $existing=$cadDoc.TextStyles.Item($styleName);$styleName='RF-TEXT-'+[guid]::NewGuid().ToString('N').Substring(0,8) } catch {}
    $style=$cadDoc.TextStyles.Add($styleName);$style.Height=0.0;$style.Width=0.8
    $style.FontFile=$fontPath;$style.SetFont($face,$false,$false,134,$pitch)
    if ($style.BigFontFile -ne '') { throw 'Unexpected Big Font on newly created TTF style' }
    if ([IO.Path]::GetFileName($style.FontFile) -ine [IO.Path]::GetFileName($fontPath)) { throw 'Font read-back mismatch' }
    $cadDoc.ActiveTextStyle=$style
    $layerNames=@{CONC='混凝土';REBAR='钢筋';STIRRUP='箍筋';DIM='标注';TEXT='文字';AXIS='轴线';ENV='内力包络';CENTER='点划轴线';HIDDEN='遮挡轮廓';ERECT='架立筋'}
    foreach ($lt in @('RF-HIDDEN','RF-CENTER','RF-ERECT')) {
        try { $null=$cadDoc.Linetypes.Item($lt) } catch { $cadDoc.Linetypes.Load($lt,(Join-Path $PSScriptRoot 'RF_LINES.lin')) }
    }
    $layers=@{}
    foreach ($key in $layerNames.Keys) {
        $layer=$cadDoc.Layers.Add('RF-'+$key+'-'+$layerNames[$key]);$layer.Color=7;$layer.Lineweight=18
        if ($key -eq 'REBAR') {$layer.Color=1;$layer.Lineweight=35}
        elseif ($key -eq 'STIRRUP') {$layer.Color=3}
        elseif ($key -eq 'CONC') {$layer.Lineweight=25}
        elseif ($key -eq 'AXIS') {$layer.Color=8;$layer.Lineweight=13}
        if ($key -eq 'CENTER') {$layer.Linetype='RF-CENTER';$layer.Color=8;$layer.Lineweight=13}
        if ($key -eq 'HIDDEN') {$layer.Linetype='RF-HIDDEN';$layer.Lineweight=13}
        if ($key -eq 'ERECT') {$layer.Linetype='RF-ERECT';$layer.Lineweight=25}
        $layers[$key]=$layer.Name
    }
    $cadDoc.SetVariable('DIMTXSTY',$styleName);$cadDoc.SetVariable('DIMTXT',110.0);$cadDoc.SetVariable('DIMASZ',80.0)
    $cadDoc.SetVariable('DIMEXO',40.0);$cadDoc.SetVariable('DIMEXE',60.0);$cadDoc.SetVariable('DIMGAP',45.0)
    $cadDoc.SetVariable('DIMDEC',0);$cadDoc.SetVariable('DIMSCALE',1.0);$cadDoc.SetVariable('DIMLFAC',1.0)
    $groupHandles=@{};$expectedText=@{};$expectedGeometry=@{}
    $count=0;$dimensions=0;$texts=0;$measurements=New-Object System.Collections.Generic.List[object]
    foreach ($group in $sceneData.groups.PSObject.Properties) {
        Write-Stage ('Drawing '+$group.Name)
        $groupHandles[$group.Name]=New-Object System.Collections.Generic.List[string]
        $off=$sceneData.offsets.($group.Name)
        foreach ($o in $group.Value) {
            $entity=$null
            switch ($o[0]) {
                LINE { $entity=$space.AddLine((Point3 $o[2] $off),(Point3 $o[3] $off)) }
                CIRCLE { $entity=$space.AddCircle((Point3 $o[2] $off),[double]$o[3]) }
                ARC {
                    $radius=[double]$o[3];$start=[double]$o[4]*[math]::PI/180;$sweep=[double]$o[5]*[math]::PI/180
                    $entity=$space.AddArc((Point3 $o[2] $off),$radius,$start,($start+$sweep))
                    if ([math]::Abs($entity.ArcLength-$radius*$sweep) -gt 0.001) {throw 'ARC length differs from shared geometry'}
                }
                POLY {
                    $coords=New-Object System.Collections.Generic.List[double]
                    foreach ($pt in $o[3]) {$coords.Add([double]$pt[0]+$off[0]);$coords.Add([double]$pt[1]+$off[1])}
                    $entity=$space.AddLightWeightPolyline([double[]]$coords.ToArray());$entity.Closed=[bool]$o[2]
                }
                TEXT { $entity=$space.AddText([string]$o[5],(Point3 $o[2] $off),[double]$o[3]);$entity.StyleName=$styleName;$entity.Rotation=[double]$o[4]*[math]::PI/180;$texts++ }
                DIM {
                    $entity=$space.AddDimRotated((Point3 $o[2] $off),(Point3 $o[3] $off),(Point3 $o[4] $off),([double]$o[5]*[math]::PI/180))
                    $factor=1.0;if ($o.Count -gt 6) {$factor=[double]$o[6]}
                    $rawMeasurement=$entity.Measurement
                    $entity.LinearScaleFactor=$factor;$entity.TextStyle=$styleName;$dimText=110.0;if ($o.Count -gt 7) {$dimText=[double]$o[7]};$entity.TextHeight=$dimText;$entity.ArrowheadSize=$dimText*0.65
                    $entity.PrimaryUnitsPrecision=3;$dimensions++
                    $angle=[double]$o[5]*[math]::PI/180
                    $expected=[math]::Abs(([double]$o[3][0]-$o[2][0])*[math]::Cos($angle)+([double]$o[3][1]-$o[2][1])*[math]::Sin($angle))
                    if ([math]::Abs($rawMeasurement-$expected) -gt 0.01) {throw ('DIM raw measurement '+$rawMeasurement+' differs from geometry '+$expected)}
                    $measurements.Add(@{handle=$entity.Handle;raw_measurement=$rawMeasurement;measurement=$entity.Measurement;scale_factor=$factor;display_value=($rawMeasurement*$factor)})
                }
                default { throw ('Unknown entity '+$o[0]) }
            }
            $entity.Layer=$layers[[string]$o[1]];$count++
            $groupHandles[$group.Name].Add($entity.Handle)
            if ($o[0] -eq 'TEXT') {$expectedText[$entity.Handle]=[string]$o[5]}
            if ($o[0] -eq 'LINE') {
                $dx=[double]$o[3][0]-$o[2][0];$dy=[double]$o[3][1]-$o[2][1]
                $expectedGeometry[$entity.Handle]=@{kind='Length';value=[math]::Sqrt($dx*$dx+$dy*$dy)}
            }
            if ($o[0] -eq 'POLY') {
                $length=0.0;$points=$o[3]
                for ($i=1;$i -lt $points.Count;$i++) {$dx=[double]$points[$i][0]-$points[$i-1][0];$dy=[double]$points[$i][1]-$points[$i-1][1];$length+=[math]::Sqrt($dx*$dx+$dy*$dy)}
                if ($o[2]) {$dx=[double]$points[0][0]-$points[-1][0];$dy=[double]$points[0][1]-$points[-1][1];$length+=[math]::Sqrt($dx*$dx+$dy*$dy)}
                $expectedGeometry[$entity.Handle]=@{kind='Length';value=$length}
            }
            if ($o[0] -eq 'ARC') {$expectedGeometry[$entity.Handle]=@{kind='ArcLength';value=([double]$o[3]*[double]$o[5]*[math]::PI/180)}}

        }
    }
    $cadDoc.Activate();$cadDoc.Regen(1);$cadApp.ZoomExtents()
    $cadDoc.SaveAs([IO.Path]::GetFullPath($OutputDwg),64)
    $cadDoc.Close($false);$cadDoc=$null
    Write-Stage 'Reopening saved drawing for verification'
    $cadDoc=$cadApp.Documents.Open([IO.Path]::GetFullPath($OutputDwg),$true)
    if ($cadDoc.ModelSpace.Count -ne $count) {throw 'Saved entity count mismatch'}
    $checkTexts=0;$checkDims=0;$checkGeometry=0
    $dimensionChecks=@{}
    foreach ($m in $measurements) {$dimensionChecks[$m.handle]=$m}
    foreach ($key in @('CENTER','HIDDEN','ERECT')) {
        if ($cadDoc.Layers.Item($layers[$key]).Linetype -ne ('RF-'+$key)) {throw 'Reopened line type mismatch'}
    }
    $savedStyle=$cadDoc.TextStyles.Item($styleName)
    if ($savedStyle.BigFontFile -ne '' -or [IO.Path]::GetFileName($savedStyle.FontFile) -ine [IO.Path]::GetFileName($fontPath)) {throw 'Reopened Chinese font mismatch'}
    foreach ($ent in $cadDoc.ModelSpace) {
        if ($expectedGeometry.ContainsKey($ent.Handle)) {
            $test=$expectedGeometry[$ent.Handle];$actual=$ent.($test.kind)
            if ([math]::Abs($actual-$test.value) -gt 0.001) {throw ('Saved geometry length mismatch '+$ent.Handle)}
            $checkGeometry++
        }
        if ($ent.ObjectName -eq 'AcDbText') {$checkTexts++;if ($ent.TextString -cne $expectedText[$ent.Handle]) {throw 'Saved Unicode text differs from scene'}}
        if ($ent.ObjectName -eq 'AcDbRotatedDimension') {
            $checkDims++;$m=$dimensionChecks[$ent.Handle]
            if ([math]::Abs($ent.Measurement-$m.measurement) -gt 0.01 -or [math]::Abs($ent.LinearScaleFactor-$m.scale_factor) -gt 0.00000001) {throw 'Reopened DIM value or scale differs'}
            if ($ent.TextOverride -ne '') {throw 'Unexpected DIM text override'}
        }
    }
    if ($checkTexts -ne $texts -or $checkDims -ne $dimensions) {throw 'Saved object type count mismatch'}
    # Native CAD render snapshots are optional; they never replace DWG checks.
    $imageWarnings=New-Object System.Collections.Generic.List[string]
    foreach ($groupName in $(if ($CapturePreview) {$groupHandles.Keys} else {@()})) {
        $selection=$null
        try {
            $items=New-Object System.Collections.Generic.List[object]
            $xmin=[double]::PositiveInfinity;$ymin=$xmin;$xmax=[double]::NegativeInfinity;$ymax=$xmax
            foreach ($handle in $groupHandles[$groupName]) {
                $ent=$cadDoc.HandleToObject($handle);$items.Add($ent);$minPoint=$null;$maxPoint=$null
                $ent.GetBoundingBox([ref]$minPoint,[ref]$maxPoint)
                $xmin=[math]::Min($xmin,$minPoint[0]);$ymin=[math]::Min($ymin,$minPoint[1]);$xmax=[math]::Max($xmax,$maxPoint[0]);$ymax=[math]::Max($ymax,$maxPoint[1])
            }
            $selection=$cadDoc.SelectionSets.Add('RFQA'+$groupName)
            $selection.Select(0,[double[]]@(($xmin-1),($ymin-1),0),[double[]]@(($xmax+1),($ymax+1),0))
            $cadDoc.Activate();$cadApp.ZoomWindow([double[]]@(($xmin-300),($ymin-300),0),[double[]]@(($xmax+300),($ymax+300),0));$cadDoc.Regen(1)
            $cadDoc.Export(([IO.Path]::GetFullPath($OutputDwg)+'_'+$groupName),'BMP',$selection)
        } catch {$imageWarnings.Add($groupName+': '+$_.Exception.Message)}
        finally {if ($null -ne $selection) {try {$selection.Delete()} catch {}}}
    }
    @{state='SUCCESS';native_preview_requested=[bool]$CapturePreview;dimension_factors_checked=$checkDims;line_types_checked=3;autocad_version=$cadApp.Version;entities=$count;dimensions=$dimensions;texts=$texts;reopened=$true;geometry_lengths_checked=$checkGeometry;image_warnings=$imageWarnings.ToArray();measurements=$measurements.ToArray()} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath ($OutputDwg+'.verify.json') -Encoding UTF8
    Write-Stage ('SUCCESS '+$OutputDwg)
} catch {
    Write-Output $_.ScriptStackTrace
    Write-Output $_.Exception.ToString()
    Write-Error $_ -ErrorAction Continue
    exit 1
} finally {
    if ($null -ne $cadDoc) {try {$cadDoc.Close($false)} catch {}}
    if ($ownApp -and $null -ne $cadApp) {try {$cadApp.Quit()} catch {}}
    [CadMessageFilter]::Revoke()
}
