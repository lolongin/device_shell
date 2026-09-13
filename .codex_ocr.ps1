$ErrorActionPreference = "Stop"

[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
Add-Type -AssemblyName System.Runtime.WindowsRuntime

$asTaskGeneric = (
    [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq "AsTask" -and
            $_.IsGenericMethod -and
            $_.GetParameters().Count -eq 1
        }
)[0]

function Await-Operation {
    param(
        [Parameter(Mandatory = $true)] $Operation,
        [Parameter(Mandatory = $true)] [Type] $ResultType
    )

    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $task = $asTask.Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}

$imagePath = "C:\Users\74527\AppData\Local\Temp\codex-clipboard-23f0f569-f7b1-480b-a584-d6e30b5fdbcc.png"
$file = Await-Operation (
    [Windows.Storage.StorageFile]::GetFileFromPathAsync($imagePath)
) ([Windows.Storage.StorageFile])
$stream = Await-Operation (
    $file.OpenAsync([Windows.Storage.FileAccessMode]::Read)
) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await-Operation (
    [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)
) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await-Operation (
    $decoder.GetSoftwareBitmapAsync()
) ([Windows.Graphics.Imaging.SoftwareBitmap])

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage(
    [Windows.Globalization.Language]::new("zh-CN")
)
if (-not $engine) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}
if (-not $engine) {
    throw "No OCR engine available."
}

$result = Await-Operation (
    $engine.RecognizeAsync($bitmap)
) ([Windows.Media.Ocr.OcrResult])

Write-Output "Language=$($engine.RecognizerLanguage.LanguageTag) Lines=$($result.Lines.Count)"
foreach ($line in $result.Lines) {
    $words = @($line.Words)
    $first = $words[0]
    $last = $words[$words.Length - 1]
    $x0 = [Math]::Round($first.BoundingRect.X)
    $y0 = [Math]::Round($first.BoundingRect.Y)
    $x1 = [Math]::Round($last.BoundingRect.X + $last.BoundingRect.Width)
    $y1 = [Math]::Round($last.BoundingRect.Y + $last.BoundingRect.Height)
    Write-Output "[$x0,$y0-$x1,$y1] $($line.Text)"
}
