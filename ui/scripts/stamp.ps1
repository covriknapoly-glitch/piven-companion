param([string]$OutputDir = "dist")

# Gives every build its own file addresses, so the window never mixes in an interface cached from another build.
$stamp = [DateTime]::UtcNow.Ticks
$html = [IO.File]::ReadAllText((Join-Path (Get-Location) "index.html"))
$html = $html.Replace('href="app.css"', "href=`"app.css?v=$stamp`"").Replace('src="app.js"', "src=`"app.js?v=$stamp`"")
$output = (Resolve-Path -LiteralPath $OutputDir).ProviderPath
$css = [IO.File]::ReadAllText((Join-Path $output "app.css"))
$iconFont = [regex]::Match($css, 'assets/SymbolsNerdFont-Icons-[A-Z0-9]+\.ttf').Value
if (!$iconFont) { throw "Could not find the bundled Piven Icons font in app.css." }
$preload = '<link rel="preload" href="{0}" as="font" type="font/ttf" crossorigin="anonymous" />' -f $iconFont
$html = $html.Replace('<link rel="stylesheet"', "$preload`n    <link rel=`"stylesheet`"")
[IO.File]::WriteAllText((Join-Path $output "index.html"), $html)
