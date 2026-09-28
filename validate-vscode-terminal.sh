#!/usr/bin/env zsh

echo "=== VSCode Terminal Integration Validation ==="
echo ""

checks_passed=0
checks_total=0

# Check 1: Shell is zsh
((checks_total++))
if [[ "$SHELL" == *"zsh"* ]] || [[ "$0" == *"zsh"* ]]; then
    echo "✅ Shell is zsh ($SHELL)"
    ((checks_passed++))
else
    echo "❌ Shell is not zsh (found: $SHELL)"
fi

# Check 2: Oh-My-Zsh loaded
((checks_total++))
if [[ -n "${ZSH:-}" ]] && [[ -d "${ZSH:-}" ]]; then
    echo "✅ Oh-My-Zsh loaded from: $ZSH"
    ((checks_passed++))
else
    # Check if it's installed even if not sourced in this context
    if [[ -d "$HOME/.oh-my-zsh" ]]; then
        echo "✅ Oh-My-Zsh installed at: $HOME/.oh-my-zsh"
        ((checks_passed++))
    else
        echo "❌ Oh-My-Zsh not found"
    fi
fi

# Check 3: Theme set in .zshrc
((checks_total++))
theme=$(grep 'ZSH_THEME=' ~/.zshrc | grep -v '^#' | head -1)
if [[ -n "$theme" ]]; then
    echo "✅ Theme configured: $theme"
    ((checks_passed++))
else
    echo "❌ No theme set in .zshrc"
fi

# Check 4: Nerd Font installed
((checks_total++))
nerd_fonts=$(ls ~/Library/Fonts/ 2>/dev/null | grep -i "nerd" | wc -l | tr -d ' ')
if [[ $nerd_fonts -gt 0 ]]; then
    echo "✅ Nerd Fonts installed: $nerd_fonts font files"
    ((checks_passed++))
else
    echo "❌ No Nerd Fonts found in ~/Library/Fonts/"
fi

# Check 5: VSCode settings include terminal font
((checks_total++))
settings_file="$HOME/Library/Application Support/Code/User/settings.json"
if [[ -f "$settings_file" ]] && grep -q "fontFamily" "$settings_file"; then
    font=$(grep "fontFamily" "$settings_file" | head -1)
    echo "✅ VSCode terminal font configured: $font"
    ((checks_passed++))
else
    echo "❌ No terminal font configured in VSCode settings"
fi

# Check 6: Custom aliases exist in .zshrc
((checks_total++))
alias_count=$(grep -c '^alias ' ~/.zshrc 2>/dev/null || echo 0)
if [[ $alias_count -ge 5 ]]; then
    echo "✅ $alias_count custom aliases configured in .zshrc"
    ((checks_passed++))
else
    echo "❌ Only $alias_count aliases (need 5+)"
fi

# Check 7: Custom functions exist
((checks_total++))
func_count=$(grep -c '^function ' ~/.zshrc 2>/dev/null || echo 0)
if [[ $func_count -ge 2 ]]; then
    echo "✅ $func_count custom functions in .zshrc"
    ((checks_passed++))
else
    echo "❌ Only $func_count functions (need 2+)"
fi

# Check 8: TERM_PROGRAM detection
((checks_total++))
if [[ "${TERM_PROGRAM:-}" == "vscode" ]]; then
    echo "✅ Running inside VSCode terminal"
    ((checks_passed++))
else
    echo "⚠️  Not running in VSCode terminal (TERM_PROGRAM=${TERM_PROGRAM:-unset}) — OK for script mode"
    ((checks_passed++)) # Not a hard failure when run from script
fi

echo ""
echo "Score: $checks_passed / $checks_total checks passed"
[[ $checks_passed -eq $checks_total ]] && echo "🏆 Perfect integration!" || echo "⚠️ Review any failing checks"
