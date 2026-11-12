# Gives every build its own file addresses, so the window never mixes in an interface cached from another build.
$stamp = [DateTime]::UtcNow.Ticks
$html = [IO.File]::ReadAllText((Join-Path (Get-Location) "index.html"))
$html = $html.Replace('href="app.css"', "href=`"app.css?v=$stamp`"").Replace('src="app.js"', "src=`"app.js?v=$stamp`"")
[IO.File]::WriteAllText((Join-Path (Get-Location) "dist\index.html"), $html)
