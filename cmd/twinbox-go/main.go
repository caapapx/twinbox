package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

func commandDisplayName(argv0 string) string {
	name := strings.TrimSpace(filepath.Base(argv0))
	if name == "" || name == "." || name == string(os.PathSeparator) {
		return "twinbox"
	}
	return name
}

func commandName() string {
	return commandDisplayName(os.Args[0])
}

func main() {
	args := os.Args[1:]
	if len(args) > 0 && args[0] == "install" {
		os.Exit(runInstall(args[1:]))
	}

	socketFlag := ""
	for len(args) > 0 && args[0] == "--socket" {
		if len(args) < 2 {
			fmt.Fprintf(os.Stderr, "%s: --socket requires a path\n", commandName())
			os.Exit(2)
		}
		socketFlag = args[1]
		args = args[2:]
	}

	socketPath := socketFlag
	if socketPath == "" {
		socketPath = defaultSocketPath()
	}

	connectTO := 3 * time.Second
	rpcTO := 30 * time.Second

	res, err := cliInvokeRPC(socketPath, args, connectTO, rpcTO)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%s: daemon rpc: %v; falling back to python\n", commandName(), err)
		fallbackExec(args)
		return
	}
	if res.Stderr != "" {
		fmt.Fprint(os.Stderr, res.Stderr)
	}
	if res.Stdout != "" {
		fmt.Print(res.Stdout)
	}
	os.Exit(res.ExitCode)
}

type fallbackCommandConfig struct {
	Dir  string
	Env  map[string]string
	Argv []string
}

func fallbackExec(argv []string) {
	py := os.Getenv("TWINBOX_PYTHON")
	if py == "" {
		py = "python3"
	}
	cfg := buildFallbackCommandConfig(argv)
	if err := validateFallbackVendorAttestation(cfg); err != nil {
		fmt.Fprintf(os.Stderr, "%s: %v\n", commandName(), err)
		os.Exit(1)
	}
	exe, err := exec.LookPath(py)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%s: no daemon and cannot find python: %v\n", commandName(), err)
		os.Exit(127)
	}
	cmd := exec.Command(exe, append([]string{"-m", "twinbox_core.task_cli"}, cfg.Argv...)...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Env = envMapToList(cfg.Env)
	cmd.Dir = cfg.Dir
	if err := cmd.Run(); err != nil {
		if x, ok := err.(*exec.ExitError); ok {
			os.Exit(x.ExitCode())
		}
		fmt.Fprintf(os.Stderr, "%s: exec: %v\n", commandName(), err)
		os.Exit(1)
	}
}

func buildFallbackCommandConfig(argv []string) fallbackCommandConfig {
	env := envListToMap(os.Environ())
	home := strings.TrimSpace(env["HOME"])
	if home == "" {
		home = os.Getenv("HOME")
	}
	profileName := parseProfileName(argv)
	if profileName != "" {
		base := strings.TrimSpace(env["TWINBOX_HOME"])
		if base == "" {
			base = filepath.Join(home, ".twinbox")
		}
		base = filepath.Clean(base)
		env["TWINBOX_HOME"] = base
		env["TWINBOX_STATE_ROOT"] = filepath.Join(base, "profiles", profileName, "state")
	}

	stateRoot := resolveStateRootFromEnvMap(env)
	if stateRoot != "" {
		env["TWINBOX_STATE_ROOT"] = stateRoot
	}
	if strings.TrimSpace(env["TWINBOX_CANONICAL_ROOT"]) == "" && stateRoot != "" {
		env["TWINBOX_CANONICAL_ROOT"] = stateRoot
	}

	codeRoot := strings.TrimSpace(env["TWINBOX_CODE_ROOT"])
	if codeRoot != "" {
		codeRoot = filepath.Clean(codeRoot)
		env["TWINBOX_CODE_ROOT"] = codeRoot
	}

	pythonPathEntries := fallbackPythonPathEntries(env, stateRoot, codeRoot)
	if len(pythonPathEntries) > 0 {
		env["PYTHONPATH"] = strings.Join(pythonPathEntries, string(os.PathListSeparator))
	}

	return fallbackCommandConfig{
		Dir:  codeRoot,
		Env:  env,
		Argv: argv,
	}
}

func parseProfileName(argv []string) string {
	for i := 0; i < len(argv); i++ {
		if argv[i] == "--profile" && i+1 < len(argv) {
			return strings.TrimSpace(argv[i+1])
		}
		if strings.HasPrefix(argv[i], "--profile=") {
			return strings.TrimSpace(strings.SplitN(argv[i], "=", 2)[1])
		}
	}
	return ""
}

func resolveStateRootFromEnvMap(env map[string]string) string {
	if root := strings.TrimSpace(env["TWINBOX_STATE_ROOT"]); root != "" {
		return filepath.Clean(root)
	}
	cfg := filepath.Join(env["HOME"], ".config", "twinbox", "state-root")
	data, err := os.ReadFile(cfg)
	if err == nil {
		line := strings.TrimSpace(string(data))
		if line != "" {
			return filepath.Clean(line)
		}
	}
	base := strings.TrimSpace(env["TWINBOX_HOME"])
	if base == "" {
		base = filepath.Join(env["HOME"], ".twinbox")
	}
	return filepath.Clean(base)
}

func fallbackPythonPathEntries(env map[string]string, stateRoot string, codeRoot string) []string {
	seen := map[string]struct{}{}
	out := []string{}
	add := func(path string) {
		path = strings.TrimSpace(path)
		if path == "" {
			return
		}
		path = filepath.Clean(path)
		if _, ok := seen[path]; ok {
			return
		}
		seen[path] = struct{}{}
		out = append(out, path)
	}

	if codeRoot != "" {
		add(filepath.Join(codeRoot, "src"))
	}
	if home := strings.TrimSpace(env["TWINBOX_HOME"]); home != "" {
		add(filepath.Join(home, "vendor"))
	}
	if stateRoot != "" {
		add(filepath.Join(stateRoot, "vendor"))
	}
	for _, entry := range filepath.SplitList(env["PYTHONPATH"]) {
		add(entry)
	}
	if home := strings.TrimSpace(env["HOME"]); home != "" {
		add(filepath.Join(home, ".twinbox", "vendor"))
	}
	return out
}

func envListToMap(items []string) map[string]string {
	out := make(map[string]string, len(items))
	for _, item := range items {
		key, value, ok := strings.Cut(item, "=")
		if !ok {
			continue
		}
		out[key] = value
	}
	return out
}

func envMapToList(env map[string]string) []string {
	out := make([]string, 0, len(env))
	for key, value := range env {
		out = append(out, key+"="+value)
	}
	return out
}

func validateFallbackVendorAttestation(cfg fallbackCommandConfig) error {
	if cfg.Dir != "" {
		srcPath := filepath.Join(cfg.Dir, "src", "twinbox_core")
		if info, err := os.Stat(srcPath); err == nil && info.IsDir() {
			return nil
		}
	}

	seen := map[string]struct{}{}
	entries := make([]string, 0)
	addEntry := func(path string) {
		path = strings.TrimSpace(path)
		if path == "" {
			return
		}
		path = filepath.Clean(path)
		if _, ok := seen[path]; ok {
			return
		}
		seen[path] = struct{}{}
		entries = append(entries, path)
	}
	for _, entry := range filepath.SplitList(cfg.Env["PYTHONPATH"]) {
		addEntry(entry)
	}
	if home := strings.TrimSpace(cfg.Env["TWINBOX_HOME"]); home != "" {
		addEntry(filepath.Join(home, "vendor"))
	}
	if stateRoot := strings.TrimSpace(cfg.Env["TWINBOX_STATE_ROOT"]); stateRoot != "" {
		addEntry(filepath.Join(stateRoot, "vendor"))
	}
	if home := strings.TrimSpace(cfg.Env["HOME"]); home != "" {
		addEntry(filepath.Join(home, ".twinbox", "vendor"))
	}

	for _, entry := range entries {
		entry = strings.TrimSpace(entry)
		if entry == "" {
			continue
		}
		pkgPath := filepath.Join(entry, "twinbox_core")
		info, err := os.Stat(pkgPath)
		if err != nil || !info.IsDir() {
			continue
		}
		manifestPath := filepath.Join(entry, "MANIFEST.json")
		body, err := os.ReadFile(manifestPath)
		if err != nil {
			return fmt.Errorf("vendor MANIFEST missing for %s", entry)
		}
		var manifest map[string]any
		if err := json.Unmarshal(body, &manifest); err != nil {
			return fmt.Errorf("vendor MANIFEST invalid for %s: %w", entry, err)
		}
		version := strings.TrimSpace(fmt.Sprint(manifest["twinbox_version"]))
		if version == "" || version == "<nil>" {
			return fmt.Errorf("vendor MANIFEST missing twinbox_version for %s", entry)
		}
		if version != twinboxProtocolVersion {
			return fmt.Errorf(
				"vendor MANIFEST twinbox_version mismatch for %s: got %s want %s",
				entry,
				version,
				twinboxProtocolVersion,
			)
		}
		return nil
	}
	return nil
}
