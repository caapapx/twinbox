package main

import (
	"encoding/json"
	"fmt"
	"io"
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

// consumeProfilePrefix returns the index of the first argument after optional --profile / --profile=.
func consumeProfilePrefix(argv []string) int {
	i := 0
	for i < len(argv) {
		a := argv[i]
		if a == "--profile" && i+1 < len(argv) {
			i += 2
			continue
		}
		if strings.HasPrefix(a, "--profile=") {
			i++
			continue
		}
		break
	}
	return i
}

// skipDaemonForTTY reports argv for commands that must read from the user's terminal.
func skipDaemonForTTY(argv []string) bool {
	i := consumeProfilePrefix(argv)
	if i >= len(argv) {
		return false
	}
	switch argv[i] {
	case "onboard", "onboarding":
		return true
	default:
		return false
	}
}

// skipDaemonLifecycleRPC: never route stop/restart through the live daemon's cli_invoke — the
// server process is torn down (or connection dies) before the JSON-RPC response, so the Go
// client sees EOF and a confusing "falling back to python" line. Run task_cli in the foreground.
func skipDaemonLifecycleRPC(argv []string) bool {
	i := consumeProfilePrefix(argv)
	if i+1 >= len(argv) || argv[i] != "daemon" {
		return false
	}
	switch argv[i+1] {
	case "stop", "restart":
		return true
	default:
		return false
	}
}

// skipDaemonStartRPC: always run `daemon start` in foreground Python. If we used RPC, a
// post-reboot lazy-start would bring the daemon up then retry RPC with argv daemon start — and
// the nested cli_invoke would see "already running" and exit 1.
func skipDaemonStartRPC(argv []string) bool {
	i := consumeProfilePrefix(argv)
	if i+1 >= len(argv) || argv[i] != "daemon" {
		return false
	}
	return argv[i+1] == "start"
}

// daemonStartArgv returns profile prefix + "daemon", "start" for lazy autostart.
func daemonStartArgv(original []string) []string {
	i := 0
	var pref []string
	for i < len(original) {
		a := original[i]
		if a == "--profile" && i+1 < len(original) {
			pref = append(pref, "--profile", original[i+1])
			i += 2
			continue
		}
		if strings.HasPrefix(a, "--profile=") {
			pref = append(pref, a)
			i++
			continue
		}
		break
	}
	out := append([]string{}, pref...)
	return append(out, "daemon", "start")
}

func shouldTryLazyDaemonStart(err error) bool {
	if err == nil {
		return false
	}
	if strings.TrimSpace(os.Getenv("TWINBOX_NO_LAZY_DAEMON")) == "1" {
		return false
	}
	s := strings.ToLower(err.Error())
	return strings.Contains(s, "no such file") ||
		strings.Contains(s, "connection refused") ||
		strings.Contains(s, "resource temporarily unavailable")
}

// tryLazyDaemonStart runs `python -m twinbox_core.task_cli daemon start` with the same env as a
// normal fallback (vendor attestation included). Stdout/stderr discarded to avoid extra noise
// when the next RPC attempt succeeds.
func tryLazyDaemonStart(cfg fallbackCommandConfig) error {
	if err := validateFallbackVendorAttestation(cfg); err != nil {
		return err
	}
	py := os.Getenv("TWINBOX_PYTHON")
	if py == "" {
		py = "python3"
	}
	exe, err := exec.LookPath(py)
	if err != nil {
		return err
	}
	startArgv := daemonStartArgv(cfg.Argv)
	cmd := exec.Command(exe, append([]string{"-m", "twinbox_core.task_cli"}, startArgv...)...)
	cmd.Env = envMapToList(cfg.Env)
	cmd.Dir = cfg.Dir
	cmd.Stdin = os.Stdin
	cmd.Stdout = io.Discard
	cmd.Stderr = io.Discard
	return cmd.Run()
}

func orchestrateExec(prefix []string, rest []string) {
	py := os.Getenv("TWINBOX_PYTHON")
	if py == "" {
		py = "python3"
	}
	synthetic := append(append([]string{}, prefix...), append([]string{"orchestrate"}, rest...)...)
	cfg := buildFallbackCommandConfig(synthetic)
	if err := validateFallbackVendorAttestation(cfg); err != nil {
		fmt.Fprintf(os.Stderr, "%s: %v\n", commandName(), err)
		os.Exit(1)
	}
	exe, err := exec.LookPath(py)
	if err != nil {
		fmt.Fprintf(os.Stderr, "%s: cannot find python: %v\n", commandName(), err)
		os.Exit(127)
	}
	cmdArgv := append([]string{"-m", "twinbox_core.orchestration"}, rest...)
	cmd := exec.Command(exe, cmdArgv...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Env = envMapToList(cfg.Env)
	cmd.Dir = cfg.Dir
	if err := cmd.Run(); err != nil {
		if x, ok := err.(*exec.ExitError); ok {
			os.Exit(x.ExitCode())
		}
		fmt.Fprintf(os.Stderr, "%s: orchestrate: %v\n", commandName(), err)
		os.Exit(1)
	}
}

func main() {
	args := os.Args[1:]
	if len(args) > 0 && args[0] == "install" {
		os.Exit(runInstall(args[1:]))
	}

	i := consumeProfilePrefix(args)
	if i < len(args) && args[i] == "orchestrate" {
		prefix := args[:i]
		rest := args[i+1:]
		orchestrateExec(prefix, rest)
		return
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

	// Some commands must not use cli_invoke: no TTY stdin (wizards), lifecycle that kills the
	// daemon (stop/restart), or explicit daemon start (avoids lazy-retry "already running").
	if skipDaemonForTTY(args) || skipDaemonLifecycleRPC(args) || skipDaemonStartRPC(args) {
		fallbackExec(args)
		return
	}

	cfg := buildFallbackCommandConfig(args)
	res, err := cliInvokeRPC(socketPath, args, connectTO, rpcTO)
	if err != nil && shouldTryLazyDaemonStart(err) {
		if lazyErr := tryLazyDaemonStart(cfg); lazyErr == nil {
			res, err = cliInvokeRPC(socketPath, args, connectTO, rpcTO)
		}
	}
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
