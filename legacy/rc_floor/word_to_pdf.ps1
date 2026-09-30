param([Parameter(Mandatory=$true)][string]$InputDocx,[Parameter(Mandatory=$true)][string]$OutputPdf)
$ErrorActionPreference='Stop'
$reportApp=$null
$reportDoc=$null
try {
    $reportApp=New-Object -ComObject Word.Application
    $reportApp.Visible=$false
    $reportApp.DisplayAlerts=0
    $reportApp.AutomationSecurity=3
    $reportDoc=$reportApp.Documents.Open([IO.Path]::GetFullPath($InputDocx),$false,$false)
    $reportDoc.Repaginate()
    foreach ($reportToc in $reportDoc.TablesOfContents) { $reportToc.Update() }
    $reportDoc.Fields.Update() | Out-Null
    $reportDoc.Repaginate()
    foreach ($reportToc in $reportDoc.TablesOfContents) { $reportToc.UpdatePageNumbers() }
    $reportDoc.Save()
    $reportDoc.ExportAsFixedFormat([IO.Path]::GetFullPath($OutputPdf),17)
    Write-Output ('PDF: '+$OutputPdf)
} finally {
    if ($null -ne $reportDoc) { $reportDoc.Close(0); [Runtime.InteropServices.Marshal]::FinalReleaseComObject($reportDoc) | Out-Null }
    if ($null -ne $reportApp) { $reportApp.Quit(); [Runtime.InteropServices.Marshal]::FinalReleaseComObject($reportApp) | Out-Null }
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
}
