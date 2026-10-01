#!/usr/bin/env zsh

echo "=== Oh-My-Zsh Plugin Validation ==="
echo ""

passed=0
failed=0

# Plugin tests
check_plugin() {
    local name="$1"
    local test_cmd="$2"
    if eval "$test_cmd" > /dev/null 2>&1; then
        echo "✅ $name - PASS"
        ((passed++))
    else
        echo "❌ $name - FAIL"
        ((failed++))
    fi
}

check_plugin "git" "[[ -d ~/.oh-my-zsh/plugins/git ]]"
check_plugin "docker" "type docker 2>/dev/null || [[ -d ~/.oh-my-zsh/plugins/docker ]]"
check_plugin "vscode" "[[ -d ~/.oh-my-zsh/plugins/vscode ]]"
check_plugin "web-search" "[[ -d ~/.oh-my-zsh/plugins/web-search ]]"
check_plugin "colored-man-pages" "[[ -d ~/.oh-my-zsh/plugins/colored-man-pages ]]"
check_plugin "jsontools" "[[ -d ~/.oh-my-zsh/plugins/jsontools ]]"
check_plugin "copypath" "[[ -d ~/.oh-my-zsh/plugins/copypath ]]"
check_plugin "zsh-autosuggestions" "[[ -d ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-autosuggestions ]]"
check_plugin "zsh-syntax-highlighting" "[[ -d ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-syntax-highlighting ]]"

echo ""
echo "Results: $passed passed, $failed failed"
[[ $failed -eq 0 ]] && echo "🏆 All plugins validated!" || echo "⚠️ Fix failing plugins before proceeding"
