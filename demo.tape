# Decepticon CLI Demo
# Usage: vhs demo.tape

Output assets/demo.gif
Output assets/demo.mp4

Require node
Require npm

Set Shell "bash"
Set FontSize 14
Set FontFamily "JetBrains Mono"
Set Width 1400
Set Height 800
Set TypingSpeed 50ms
Set Theme "Catppuccin Mocha"
Set Padding 20

# Start CLI
Type "cd clients/cli && npm run dev"
Enter
Sleep 3s

# First interaction
Type "Conduct a red team test against the target 172.22.0.3. The environment is a known vulnerable system, Metasploitable2, and has been set up for demonstration purposes."
Sleep 1s
Enter

# Wait for agent response to complete (prompt reappears)
Sleep 60s

# Show help
Type "/help"
Enter
Sleep 3s

# Exit
Ctrl+C
Sleep 2s
