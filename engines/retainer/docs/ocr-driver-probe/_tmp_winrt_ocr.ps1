$out = 'D:\workbuddy测试\_ocr_winrt_result.txt'
$log = New-Object System.Collections.ArrayList

try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  [void]$log.Add("step1 runtime loaded")

  [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
  [void]$log.Add("step2 ocr type loaded")

  $ext = [System.WindowsRuntimeSystemExtensions]
  [void]$log.Add("step3 extensions type = " + $ext.FullName)

  $cands = @($ext.GetMethods() | Where-Object {
      $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -like 'IAsyncOperation*'
    })
  [void]$log.Add("step4 AsTask candidates = " + $cands.Count)
  $asTaskGeneric = $cands[0]
  [void]$log.Add("step5 using = " + $asTaskGeneric.ToString())

  function Await($op, $type) {
    $m = $asTaskGeneric.MakeGenericMethod($type)
    $t = $m.Invoke($null, @($op))
    $t.Wait(-1) | Out-Null
    $t.Result
  }

  $langs = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages)
  [void]$log.Add("step6 langs = " + (($langs | ForEach-Object { $_.LanguageTag }) -join ','))
  $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
  [void]$log.Add("step7 engine = " + ($null -ne $engine) + " lang = " + $engine.RecognizerLanguage.LanguageTag)

  [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
  [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] | Out-Null
  [void]$log.Add("step8 storage types loaded")

  foreach ($img in @('D:\workbuddy测试\_tmp_ocr_license.png', 'D:\workbuddy测试\_tmp_ocr_idcard.png')) {
    try {
      $sw = [System.Diagnostics.Stopwatch]::StartNew()
      $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($img)) ([Windows.Storage.StorageFile])
      $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
      $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
      $bmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
      $res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
      $sw.Stop()
      [void]$log.Add("IMAGE " + (Split-Path $img -Leaf) + " ms=" + $sw.ElapsedMilliseconds + " lines=" + $res.Lines.Count)
      foreach ($line in $res.Lines) { [void]$log.Add("  | " + $line.Text) }
      $stream.Dispose()
    }
    catch { [void]$log.Add("IMAGE ERR " + (Split-Path $img -Leaf) + " : " + $_.Exception.Message) }
  }
}
catch {
  [void]$log.Add("FATAL: " + $_.Exception.Message)
  [void]$log.Add("AT: " + $_.InvocationInfo.PositionMessage)
}

$log -join "`r`n" | Set-Content -Path $out -Encoding UTF8
