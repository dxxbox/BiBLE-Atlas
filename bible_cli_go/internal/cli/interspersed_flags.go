package cli

import (
	"flag"
	"strings"
)

type boolFlag interface {
	IsBoolFlag() bool
}

// parseFlagSet accepts flags before or after positional arguments.
// The standard flag package stops parsing at the first positional argument,
// but CLI users naturally write commands like `download name --output dir`.
func parseFlagSet(fs *flag.FlagSet, args []string) error {
	return fs.Parse(reorderInterspersedFlags(fs, args))
}

func reorderInterspersedFlags(fs *flag.FlagSet, args []string) []string {
	flags := make([]string, 0, len(args))
	positionals := make([]string, 0, len(args))

	for i := 0; i < len(args); i++ {
		arg := args[i]
		if arg == "--" {
			positionals = append(positionals, args[i+1:]...)
			break
		}
		if !isFlagToken(arg) {
			positionals = append(positionals, arg)
			continue
		}

		flags = append(flags, arg)
		if flagRequiresValue(fs, arg) && i+1 < len(args) {
			i++
			flags = append(flags, args[i])
		}
	}

	return append(flags, positionals...)
}

func isFlagToken(arg string) bool {
	return strings.HasPrefix(arg, "-") && arg != "-"
}

func flagRequiresValue(fs *flag.FlagSet, arg string) bool {
	name, hasInlineValue := flagName(arg)
	if hasInlineValue {
		return false
	}
	f := fs.Lookup(name)
	if f == nil {
		return false
	}
	if bf, ok := f.Value.(boolFlag); ok && bf.IsBoolFlag() {
		return false
	}
	return true
}

func flagName(arg string) (string, bool) {
	name := strings.TrimLeft(arg, "-")
	if idx := strings.Index(name, "="); idx >= 0 {
		return name[:idx], true
	}
	return name, false
}
