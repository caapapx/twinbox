package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

func main() {
	socketFlag := ""
	args := os.Args[1:]
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
	cmd := exec.Command(exe, append([]string{"-m", "twinbox_core.task_cli"}, argv...)...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	cmd.Env = os.Environ()
	// Prefer repo cwd if set; else leave default
	if cr := os.Getenv("TWINBOX_CODE_ROOT"); cr != "" {
		cmd.Dir = filepath.Clean(cr)
	}
	if err := cmd.Run(); err != nil {
		if x, ok := err.(*exec.ExitError); ok {
			os.Exit(x.ExitCode())
		}
		fmt.Fprintf(os.Stderr, "twinbox-go: exec: %v\n", err)
		os.Exit(1)
	}
}
