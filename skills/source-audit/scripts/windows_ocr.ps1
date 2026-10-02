param([Parameter(Mandatory=$true)][string]$ImageFile,
      [Parameter(Mandatory=$true)][string]$OutputJson,
      [string]$LanguageTag='zh-Hans-CN')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait()
    $task.Result
}
$language = New-Object Windows.Globalization.Language($LanguageTag)
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
$actualTag = $LanguageTag
if ($null -eq $engine -and $LanguageTag -eq 'en-US') {
    $language = New-Object Windows.Globalization.Language('zh-Hans-CN')
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
    $actualTag = 'zh-Hans-CN'
}
if ($null -eq $engine) { throw ('OCR language pack unavailable: '+$LanguageTag) }
$stream = $null
$bitmap = $null
try {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Resolve-Path -LiteralPath $ImageFile).Path)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $ocr = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $text = (@($ocr.Lines | ForEach-Object { $_.Text }) -join "`n")
    @{ text=$text; method=('Windows OCR '+$actualTag); requested_language=$LanguageTag;
       actual_language=$actualTag; language_fallback=($actualTag -ne $LanguageTag); reviewed=$false } |
        ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $OutputJson -Encoding UTF8
} finally {
    if ($null -ne $bitmap) { $bitmap.Dispose() }
    if ($null -ne $stream) { $stream.Dispose() }
}
