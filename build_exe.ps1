# Gera o executável dist\sentinela\sentinela.exe (Windows).
# Uso:  powershell -ExecutionPolicy Bypass -File build_exe.ps1
# Pré-requisito: pip install -r requirements.txt

$ErrorActionPreference = "Stop"

pyinstaller --noconfirm --clean --onefile --name sentinela --icon "docs/imagens/logo.ico" `
    --add-data "sentinela/templates;sentinela/templates" `
    --add-data "sentinela/painel/templates;sentinela/painel/templates" `
    --add-data "sentinela/painel/static;sentinela/painel/static" `
    --collect-submodules faker.providers `
    --collect-data axe_playwright_python `
    --collect-submodules selenium `
    --collect-data selenium `
    --collect-submodules _pytest `
    --collect-submodules pluggy `
    --hidden-import pytest `
    --collect-submodules google.genai `
    --hidden-import comtypes.stream `
    --hidden-import pywinauto.controls.uia_controls `
    sentinela_exe.py

# Pasta pronta para distribuir: exe + roteiros de exemplo + modelo do .env + README
$destino = "dist\sentinela"
New-Item -ItemType Directory -Force $destino | Out-Null
try { Move-Item -Force "dist\sentinela.exe" "$destino\sentinela.exe" -ErrorAction Stop } catch { Write-Warning "O sentinela.exe antigo está aberto — feche-o e mova dist\sentinela.exe para $destino" }
Copy-Item -Recurse -Force "roteiros" "$destino\roteiros"
Copy-Item -Recurse -Force "site_treino" "$destino\site_treino"

Copy-Item -Recurse -Force "sistemas_treino" "$destino\sistemas_treino"

# Exemplos de outros frameworks, sem node_modules nem resultados

robocopy exemplos_frameworks "$destino\exemplos_frameworks" /E /XD node_modules resultados test-results target /NFL /NDL /NJH /NJS | Out-Null
Copy-Item -Force ".env.exemplo" "$destino\.env.exemplo"
Copy-Item -Force "README.md" "$destino\README.md"
Copy-Item -Force "README.en.md" "$destino\README.en.md"
Write-Host "Pronto: $destino\sentinela.exe  (dois cliques abrem o painel no navegador)"
