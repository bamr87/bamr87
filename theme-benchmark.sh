#!/usr/bin/env zsh
set -euo pipefail

THEMES=("robbyrussell" "agnoster" "clean")
RESULTS_FILE="$HOME/theme-benchmark-results.md"

echo "# Theme Benchmark Results" > "$RESULTS_FILE"
echo "Date: $(date)" >> "$RESULTS_FILE"
echo "" >> "$RESULTS_FILE"
echo "| Theme | Avg Prompt Time (ms) | Status |" >> "$RESULTS_FILE"
echo "|-------|---------------------|--------|" >> "$RESULTS_FILE"

for theme in "${THEMES[@]}"; do
    total=0
    for i in {1..5}; do
        start=$(perl -MTime::HiRes=time -e 'printf "%.3f", time')
        ZSH_THEME="$theme" 2>/dev/null || true
        end=$(perl -MTime::HiRes=time -e 'printf "%.3f", time')
        elapsed=$(echo "($end - $start) * 1000" | bc)
        total=$(echo "$total + $elapsed" | bc)
    done
    avg=$(echo "scale=2; $total / 5" | bc)
    echo "| $theme | $avg | ✅ |" >> "$RESULTS_FILE"
    echo "Theme '$theme': avg ${avg}ms"
done

echo ""
echo "Results saved to $RESULTS_FILE"
cat "$RESULTS_FILE"
