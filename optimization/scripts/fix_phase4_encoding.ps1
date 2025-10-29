#Requires -Version 5.1

<#
.SYNOPSIS
    Fix PowerShell script encoding issues and remove hidden characters

.DESCRIPTION
    This utility script normalizes file encoding to UTF-8 (no BOM) with CRLF line endings
    and removes hidden characters that may cause script execution failures.

.PARAMETER FilePath
    Path to file to fix (default: optimization/scripts/run_phase4.ps1)

.PARAMETER BackupOriginal
    Create .backup file before modifying

.PARAMETER Verify
    Only verify encoding, don't modify

.EXAMPLE
    .\fix_phase4_encoding.ps1 -BackupOriginal
    Fix encoding with backup of original file

.EXAMPLE
    .\fix_phase4_encoding.ps1 -Verify
    Verify encoding without making changes

.EXAMPLE
    .\fix_phase4_encoding.ps1 -FilePath optimization/scripts/run_phase3.ps1 -BackupOriginal
    Fix specific file with backup

.NOTES
    Author: PowerShell Encoding Fixer
    Version: 1.0
    Requires: PowerShell 5.1+
#>

param(
    [string]$FilePath = "optimization/scripts/run_phase4.ps1",
    [switch]$BackupOriginal,
    [switch]$Verify
)

# Script configuration
$ScriptName = "PowerShell Encoding Fixer"
$Version = "1.0"
$StartTime = Get-Date

Write-Host "=== $ScriptName v$Version ===" -ForegroundColor Green
Write-Host "Target file: $FilePath"
Write-Host "Backup original: $BackupOriginal"
Write-Host "Verify only: $Verify"
Write-Host ""

# Check if file exists
if (-not (Test-Path $FilePath)) {
    Write-Host "Error: File not found: $FilePath" -ForegroundColor Red
    exit 1
}

try {
    # Read file as byte array for encoding detection
    Write-Host "Reading file for encoding analysis..."
    $fileBytes = [System.IO.File]::ReadAllBytes($FilePath)
    $fileContent = [System.IO.File]::ReadAllText($FilePath)
    
    # Encoding detection
    Write-Host "Detecting current encoding..."
    
    $hasBOM = $false
    $bomType = "None"
    $lineEndings = "Unknown"
    
    # Check for BOM (Byte Order Mark)
    if ($fileBytes.Length -ge 3 -and $fileBytes[0] -eq 0xEF -and $fileBytes[1] -eq 0xBB -and $fileBytes[2] -eq 0xBF) {
        $hasBOM = $true
        $bomType = "UTF-8 BOM"
    }
    elseif ($fileBytes.Length -ge 2 -and $fileBytes[0] -eq 0xFF -and $fileBytes[1] -eq 0xFE) {
        $hasBOM = $true
        $bomType = "UTF-16 LE BOM"
    }
    elseif ($fileBytes.Length -ge 2 -and $fileBytes[0] -eq 0xFE -and $fileBytes[1] -eq 0xFF) {
        $hasBOM = $true
        $bomType = "UTF-16 BE BOM"
    }
    
    # Detect line endings
    $crlfCount = 0
    $lfCount = 0
    $crCount = 0
    
    for ($i = 0; $i -lt $fileBytes.Length - 1; $i++) {
        if ($fileBytes[$i] -eq 0x0D -and $fileBytes[$i + 1] -eq 0x0A) {
            $crlfCount++
        }
        elseif ($fileBytes[$i] -eq 0x0A) {
            $lfCount++
        }
        elseif ($fileBytes[$i] -eq 0x0D) {
            $crCount++
        }
    }
    
    if ($crlfCount -gt $lfCount -and $crlfCount -gt $crCount) {
        $lineEndings = "CRLF (Windows)"
    }
    elseif ($lfCount -gt $crCount) {
        $lineEndings = "LF (Unix)"
    }
    elseif ($crCount -gt 0) {
        $lineEndings = "CR (Mac)"
    }
    
    Write-Host "Current encoding: $bomType" -ForegroundColor Yellow
    Write-Host "Current line endings: $lineEndings" -ForegroundColor Yellow
    
    # Hidden character detection
    Write-Host "Scanning for hidden characters..."
    
    $hiddenChars = @()
    $problematicLines = @()
    
    # Check for problematic characters
    $lines = $fileContent -split "`n"
    for ($lineNum = 0; $lineNum -lt $lines.Count; $lineNum++) {
        $line = $lines[$lineNum]
        $lineChars = $line.ToCharArray()
        
        for ($charIndex = 0; $charIndex -lt $lineChars.Count; $charIndex++) {
            $char = $lineChars[$charIndex]
            $charCode = [int][char]$char
            
            # Check for problematic characters
            if ($charCode -eq 0x200B -or $charCode -eq 0x200C -or $charCode -eq 0x200D) {
                # Zero-width spaces
                $hiddenChars += "Zero-width space (U+$($charCode.ToString('X4'))) at line $($lineNum + 1), position $($charIndex + 1)"
                $problematicLines += $lineNum + 1
            }
            elseif ($charCode -eq 0x00A0) {
                # Non-breaking space
                $hiddenChars += "Non-breaking space (U+$($charCode.ToString('X4'))) at line $($lineNum + 1), position $($charIndex + 1)"
                $problematicLines += $lineNum + 1
            }
            elseif ($charCode -eq 0xFEFF) {
                # Byte Order Mark in middle of file
                $hiddenChars += "BOM in middle of file (U+$($charCode.ToString('X4'))) at line $($lineNum + 1), position $($charIndex + 1)"
                $problematicLines += $lineNum + 1
            }
            elseif ($charCode -lt 32 -and $charCode -ne 9 -and $charCode -ne 10 -and $charCode -ne 13) {
                # Control characters (except tab, newline, carriage return)
                $hiddenChars += "Control character (U+$($charCode.ToString('X4'))) at line $($lineNum + 1), position $($charIndex + 1)"
                $problematicLines += $lineNum + 1
            }
        }
    }
    
    if ($hiddenChars.Count -gt 0) {
        Write-Host "Found $($hiddenChars.Count) hidden characters:" -ForegroundColor Red
        foreach ($char in $hiddenChars) {
            Write-Host "  $char" -ForegroundColor Red
        }
        
        # Check specifically mentioned lines (343-347)
        $specificLines = @(343, 344, 345, 346, 347)
        $foundInSpecificLines = $problematicLines | Where-Object { $_ -in $specificLines }
        if ($foundInSpecificLines.Count -gt 0) {
            Write-Host "  Hidden characters found in lines 343-347: $($foundInSpecificLines -join ', ')" -ForegroundColor Red
        }
    }
    else {
        Write-Host "No hidden characters found" -ForegroundColor Green
    }
    
    # If verify only, exit here
    if ($Verify) {
        Write-Host ""
        Write-Host "=== VERIFICATION SUMMARY ===" -ForegroundColor Cyan
        Write-Host "File: $FilePath"
        Write-Host "Encoding: $bomType"
        Write-Host "Line endings: $lineEndings"
        Write-Host "Hidden characters: $($hiddenChars.Count)"
        Write-Host ""
        
        if ($hasBOM -or $lineEndings -ne "CRLF (Windows)" -or $hiddenChars.Count -gt 0) {
            Write-Host "Status: NEEDS FIXING" -ForegroundColor Red
            exit 1
        }
        else {
            Write-Host "Status: OK" -ForegroundColor Green
            exit 0
        }
    }
    
    # Create backup if requested
    if ($BackupOriginal) {
        $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $backupPath = "$FilePath.backup.$timestamp"
        
        Write-Host "Creating backup: $backupPath"
        Copy-Item $FilePath $backupPath
        Write-Host "Backup created successfully" -ForegroundColor Green
    }
    
    # Encoding normalization
    Write-Host "Normalizing encoding and line endings..."
    
    # Remove BOM if present
    if ($hasBOM) {
        $fileContent = $fileContent.TrimStart([char]0xFEFF)
        Write-Host "Removed BOM" -ForegroundColor Yellow
    }
    
    # Remove hidden characters
    $originalLength = $fileContent.Length
    $fileContent = $fileContent -replace "[\u200B-\u200D]", ""  # Zero-width spaces
    $fileContent = $fileContent -replace "[\u00A0]", " "        # Non-breaking spaces
    $fileContent = $fileContent -replace "[\uFEFF]", ""        # BOM in middle
    $fileContent = $fileContent -replace "[\u0000-\u0008\u000B\u000C\u000E-\u001F]", ""  # Control characters except tab, newline, CR
    
    $removedChars = $originalLength - $fileContent.Length
    if ($removedChars -gt 0) {
        Write-Host "Removed $removedChars hidden characters" -ForegroundColor Yellow
    }
    
    # Normalize line endings
    Write-Host "Normalizing line endings to CRLF..."
    $fileContent = $fileContent -replace "`r`n", "`n"  # Normalize CRLF to LF first
    $fileContent = $fileContent -replace "`r", "`n"   # Normalize CR to LF
    $fileContent = $fileContent -replace "`n", "`r`n" # Convert LF to CRLF
    
    # Write file with UTF-8 encoding (no BOM)
    Write-Host "Writing file with UTF-8 encoding (no BOM)..."
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($FilePath, $fileContent, $utf8NoBom)
    
    Write-Host "File encoding normalized" -ForegroundColor Green
    
    # Verification
    Write-Host "Verifying changes..."
    
    # Re-read file and verify
    $newFileBytes = [System.IO.File]::ReadAllBytes($FilePath)
    $newFileContent = [System.IO.File]::ReadAllText($FilePath)
    
    # Check for BOM
    $hasNewBOM = $false
    if ($newFileBytes.Length -ge 3 -and $newFileBytes[0] -eq 0xEF -and $newFileBytes[1] -eq 0xBB -and $newFileBytes[2] -eq 0xBF) {
        $hasNewBOM = $true
    }
    
    # Check line endings
    $newCrlfCount = 0
    $newLfCount = 0
    $newCrCount = 0
    
    for ($i = 0; $i -lt $newFileBytes.Length - 1; $i++) {
        if ($newFileBytes[$i] -eq 0x0D -and $newFileBytes[$i + 1] -eq 0x0A) {
            $newCrlfCount++
        }
        elseif ($newFileBytes[$i] -eq 0x0A) {
            $newLfCount++
        }
        elseif ($newFileBytes[$i] -eq 0x0D) {
            $newCrCount++
        }
    }
    
    $newLineEndings = "Unknown"
    if ($newCrlfCount -gt $newLfCount -and $newCrlfCount -gt $newCrCount) {
        $newLineEndings = "CRLF (Windows)"
    }
    elseif ($newLfCount -gt $newCrCount) {
        $newLineEndings = "LF (Unix)"
    }
    elseif ($newCrCount -gt 0) {
        $newLineEndings = "CR (Mac)"
    }
    
    # Check for remaining hidden characters
    $newHiddenChars = @()
    $newLines = $newFileContent -split "`n"
    for ($lineNum = 0; $lineNum -lt $newLines.Count; $lineNum++) {
        $line = $newLines[$lineNum]
        $lineChars = $line.ToCharArray()
        
        for ($charIndex = 0; $charIndex -lt $lineChars.Count; $charIndex++) {
            $char = $lineChars[$charIndex]
            $charCode = [int][char]$char
            
            if ($charCode -eq 0x200B -or $charCode -eq 0x200C -or $charCode -eq 0x200D -or 
                $charCode -eq 0x00A0 -or $charCode -eq 0xFEFF -or 
                ($charCode -lt 32 -and $charCode -ne 9 -and $charCode -ne 10 -and $charCode -ne 13)) {
                $newHiddenChars += "U+$($charCode.ToString('X4')) at line $($lineNum + 1), position $($charIndex + 1)"
            }
        }
    }
    
    Write-Host "Verification results:"
    Write-Host "  BOM present: $hasNewBOM" -ForegroundColor $(if ($hasNewBOM) { "Red" } else { "Green" })
    Write-Host "  Line endings: $newLineEndings" -ForegroundColor $(if ($newLineEndings -eq "CRLF (Windows)") { "Green" } else { "Red" })
    Write-Host "  Hidden characters: $($newHiddenChars.Count)" -ForegroundColor $(if ($newHiddenChars.Count -eq 0) { "Green" } else { "Red" })
    
    if ($newHiddenChars.Count -gt 0) {
        Write-Host "  Remaining hidden characters:" -ForegroundColor Red
        foreach ($char in $newHiddenChars) {
            Write-Host "    $char" -ForegroundColor Red
        }
    }
    
    # Syntax validation
    Write-Host "Validating PowerShell syntax..."
    
    try {
        $syntaxTest = powershell -NoProfile -Command "& { . '$FilePath' -DryRun }" 2>&1
        $syntaxExitCode = $LASTEXITCODE
        
        if ($syntaxExitCode -eq 0) {
            Write-Host "PowerShell syntax validation: PASS" -ForegroundColor Green
        }
        else {
            Write-Host "PowerShell syntax validation: FAIL" -ForegroundColor Red
            Write-Host "Syntax errors:" -ForegroundColor Red
            $syntaxTest | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
            
            # Restore from backup if available
            if ($BackupOriginal -and (Test-Path "$FilePath.backup.$timestamp")) {
                Write-Host "Restoring from backup due to syntax errors..." -ForegroundColor Yellow
                Copy-Item "$FilePath.backup.$timestamp" $FilePath
                Write-Host "File restored from backup" -ForegroundColor Yellow
            }
            
            Write-Host "Please review the file manually for syntax issues" -ForegroundColor Red
            exit 2
        }
    }
    catch {
        Write-Host "PowerShell syntax validation failed: $_" -ForegroundColor Red
        exit 2
    }
    
    # Summary report
    Write-Host ""
    Write-Host "=== ENCODING FIX SUMMARY ===" -ForegroundColor Cyan
    Write-Host "File: $FilePath"
    Write-Host "Original encoding: $bomType"
    Write-Host "New encoding: UTF-8 (no BOM)"
    Write-Host "Original line endings: $lineEndings"
    Write-Host "New line endings: CRLF"
    Write-Host "Hidden characters removed: $removedChars"
    Write-Host "Syntax validation: PASS"
    if ($BackupOriginal) {
        Write-Host "Backup created: $backupPath"
    }
    else {
        Write-Host "Backup created: N/A"
    }
    
    # Final status
    if (-not $hasNewBOM -and $newLineEndings -eq "CRLF (Windows)" -and $newHiddenChars.Count -eq 0) {
        Write-Host ""
        Write-Host "Status: SUCCESS - File ready for execution" -ForegroundColor Green
        exit 0
    }
    else {
        Write-Host ""
        Write-Host "Status: PARTIAL - Some issues remain" -ForegroundColor Yellow
        exit 1
    }
}
catch {
    Write-Host "Fatal error during encoding fix: $_" -ForegroundColor Red
    Write-Host "Stack trace: $($_.ScriptStackTrace)" -ForegroundColor Red
    exit 1
}
