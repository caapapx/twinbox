package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

func main() {
	args := os.Args[1:]
	if len(args) > 0 && args[0] == "install" {
		os.Exit(runInstall(args[1:]))
	}

	socketFlag := ""
	for len(args) > 0 && args[0] == "--socket" {
		if len(args) < 2 {
			fmt.Fprintln(os.Stderr, "twinbox-go: --socket requires a path")
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
		fmt.Fprintf(os.Stderr, "twinbox-go: daemon rpc: %v; falling back to python\n", err)
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
	exe, err := exec.LookPath(py)
	if err != nil {
		fmt.Fprintf(os.Stderr, "twinbox-go: no daemon and cannot find python: %v\n", err)
		os.Exit(127)
	}
	cfg := buildFallbackCommandConfig(argv)
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
		fmt.Fprintf(os.Stderr, "twinbox-go: exec: %v\n", err)
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
