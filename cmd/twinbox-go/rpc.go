package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"time"
)

const twinboxProtocolVersion = "0.1.0"

type rpcRequest struct {
	JSONRPC        string         `json:"jsonrpc"`
	Method         string         `json:"method"`
	Params         map[string]any `json:"params"`
	ID             int            `json:"id"`
	TwinboxVersion string         `json:"twinbox_version"`
}

type rpcResponse struct {
	JSONRPC        string        `json:"jsonrpc"`
	ID             int           `json:"id"`
	TwinboxVersion string        `json:"twinbox_version"`
	Result         *invokeResult `json:"result,omitempty"`
	Error          *rpcErrorObj  `json:"error,omitempty"`
}

type invokeResult struct {
	ExitCode int    `json:"exit_code"`
	Stdout   string `json:"stdout"`
	Stderr   string `json:"stderr"`
}

type rpcErrorObj struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

func defaultSocketPath() string {
	if s := os.Getenv("TWINBOX_DAEMON_SOCKET"); s != "" {
		return s
	}
	if root := os.Getenv("TWINBOX_STATE_ROOT"); root != "" {
		return filepath.Join(root, "run", "daemon.sock")
	}
	cfg := filepath.Join(os.Getenv("HOME"), ".config", "twinbox", "state-root")
	data, err := os.ReadFile(cfg)
	if err != nil || len(data) == 0 {
		return filepath.Join(os.Getenv("HOME"), ".twinbox", "run", "daemon.sock")
	}
	line := string(data)
	for i, c := range line {
		if c == '\n' || c == '\r' {
			line = line[:i]
			break
		}
	}
	line = filepath.Clean(line)
	return filepath.Join(line, "run", "daemon.sock")
}

func cliInvokeRPC(socketPath string, argv []string, connectTimeout, rpcTimeout time.Duration) (*invokeResult, error) {
	d := net.Dialer{Timeout: connectTimeout}
	conn, err := d.Dial("unix", socketPath)
	if err != nil {
		return nil, err
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(rpcTimeout))

	req := rpcRequest{
		JSONRPC:        "2.0",
		Method:         "cli_invoke",
		Params:         map[string]any{"argv": argv},
		ID:             1,
		TwinboxVersion: twinboxProtocolVersion,
	}
	body, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}
	if _, err := conn.Write(append(body, '\n')); err != nil {
		return nil, err
	}
	br := bufio.NewReader(conn)
	line, err := br.ReadBytes('\n')
	if err != nil {
		return nil, err
	}
	var resp rpcResponse
	if err := json.Unmarshal(line, &resp); err != nil {
		return nil, fmt.Errorf("rpc decode: %w", err)
	}
	if resp.Error != nil {
		return nil, fmt.Errorf("rpc error %d: %s", resp.Error.Code, resp.Error.Message)
	}
	if resp.Result == nil {
		return nil, fmt.Errorf("rpc: empty result")
	}
	return resp.Result, nil
}
