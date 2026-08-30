Add-Type -AssemblyName System.Drawing

$resourceRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'resources'
$size = 256
$bitmap = [System.Drawing.Bitmap]::new($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)

try {
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.Clear([System.Drawing.Color]::Transparent)

    $blue = [System.Drawing.Color]::FromArgb(255, 9, 105, 169)
    $white = [System.Drawing.Color]::White
    $graphics.FillEllipse([System.Drawing.SolidBrush]::new($blue), 4, 4, 248, 248)

    $promptPen = [System.Drawing.Pen]::new($white, 18)
    $promptPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $promptPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $promptPen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
    $graphics.DrawLines($promptPen, [System.Drawing.PointF[]]@(
        [System.Drawing.PointF]::new(75, 83),
        [System.Drawing.PointF]::new(132, 128),
        [System.Drawing.PointF]::new(75, 173)
    ))

    $underscorePen = [System.Drawing.Pen]::new($white, 15)
    $underscorePen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $underscorePen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $graphics.DrawLine($underscorePen, 150, 174, 196, 174)

    $pngPath = Join-Path $resourceRoot 'odyterm-icon.png'
    $bitmap.Save($pngPath, [System.Drawing.Imaging.ImageFormat]::Png)

    $icoPath = Join-Path $resourceRoot 'odyterm-icon.ico'
    $pngBytes = [System.IO.File]::ReadAllBytes($pngPath)
    $icoHeader = New-Object byte[] 22
    $icoHeader[2] = 1 # ICO type
    $icoHeader[4] = 1 # One image
    $icoHeader[10] = 1 # One color plane
    $icoHeader[12] = 32 # 32-bit color
    [System.Array]::Copy([System.BitConverter]::GetBytes([uint32]$pngBytes.Length), 0, $icoHeader, 14, 4)
    [System.Array]::Copy([System.BitConverter]::GetBytes([uint32]22), 0, $icoHeader, 18, 4)

    $icoBytes = New-Object byte[] (22 + $pngBytes.Length)
    [System.Array]::Copy($icoHeader, 0, $icoBytes, 0, $icoHeader.Length)
    [System.Array]::Copy($pngBytes, 0, $icoBytes, 22, $pngBytes.Length)
    [System.IO.File]::WriteAllBytes($icoPath, $icoBytes)
} finally {
    $graphics.Dispose()
    $bitmap.Dispose()
}
