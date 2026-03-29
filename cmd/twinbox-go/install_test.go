package main

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRunInstallAcceptsHTTPArchiveSource(t *testing.T) {
	stateRoot := t.TempDir()
	archiveBytes := buildTwinboxCoreTarball(t)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/twinbox_core.tar.gz" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/gzip")
		_, _ = w.Write(archiveBytes)
	}))
	defer server.Close()

	exitCode := runInstall([]string{
		"--state-root", stateRoot,
		"--archive", server.URL + "/twinbox_core.tar.gz",
	})

	if exitCode != 0 {
		t.Fatalf("runInstall() exit = %d, want 0", exitCode)
	}
	pkgRoot := filepath.Join(stateRoot, "vendor", "twinbox_core")
	assertFileContains(t, filepath.Join(pkgRoot, "__init__.py"), "# pkg")
	assertFileContains(t, filepath.Join(pkgRoot, "task_cli.py"), "VALUE = 42")
	manifestPath := filepath.Join(stateRoot, "vendor", "MANIFEST.json")
	assertFileContains(t, manifestPath, "\"twinbox_version\": \""+twinboxProtocolVersion+"\"")
}

func TestBuildFallbackCommandConfigPrefersCodeRootSrcAndStateVendor(t *testing.T) {
	home := t.TempDir()
	codeRoot := filepath.Join(home, "repo")
	stateRoot := filepath.Join(home, "state")

	t.Setenv("HOME", home)
	t.Setenv("TWINBOX_CODE_ROOT", codeRoot)
	t.Setenv("TWINBOX_STATE_ROOT", stateRoot)
	t.Setenv("PYTHONPATH", "/already/here")

	cfg := buildFallbackCommandConfig([]string{"task", "todo", "--json"})

	if cfg.Dir != codeRoot {
		t.Fatalf("Dir = %q, want %q", cfg.Dir, codeRoot)
	}
	if got, want := cfg.Env["TWINBOX_STATE_ROOT"], stateRoot; got != want {
		t.Fatalf("TWINBOX_STATE_ROOT = %q, want %q", got, want)
	}
	if got, want := cfg.Env["TWINBOX_CANONICAL_ROOT"], stateRoot; got != want {
		t.Fatalf("TWINBOX_CANONICAL_ROOT = %q, want %q", got, want)
	}
	pyPath := strings.Split(cfg.Env["PYTHONPATH"], string(os.PathListSeparator))
	wantPrefix := []string{
		filepath.Join(codeRoot, "src"),
		filepath.Join(stateRoot, "vendor"),
		"/already/here",
	}
	if len(pyPath) < len(wantPrefix) {
		t.Fatalf("PYTHONPATH entries = %v, want prefix %v", pyPath, wantPrefix)
	}
	for i, want := range wantPrefix {
		if pyPath[i] != want {
			t.Fatalf("PYTHONPATH[%d] = %q, want %q (full=%v)", i, pyPath[i], want, pyPath)
		}
	}
}

func TestBuildFallbackCommandConfigAppliesProfileBeforePythonImport(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("PYTHONPATH", "")
	t.Setenv("TWINBOX_STATE_ROOT", "")
	t.Setenv("TWINBOX_HOME", "")
	t.Setenv("TWINBOX_CODE_ROOT", "")

	cfg := buildFallbackCommandConfig([]string{"--profile", "work", "task", "todo"})

	wantHome := filepath.Join(home, ".twinbox")
	wantState := filepath.Join(wantHome, "profiles", "work", "state")
	if got := cfg.Env["TWINBOX_HOME"]; got != wantHome {
		t.Fatalf("TWINBOX_HOME = %q, want %q", got, wantHome)
	}
	if got := cfg.Env["TWINBOX_STATE_ROOT"]; got != wantState {
		t.Fatalf("TWINBOX_STATE_ROOT = %q, want %q", got, wantState)
	}
	if got := cfg.Env["TWINBOX_CANONICAL_ROOT"]; got != wantState {
		t.Fatalf("TWINBOX_CANONICAL_ROOT = %q, want %q", got, wantState)
	}
	pyPath := strings.Split(cfg.Env["PYTHONPATH"], string(os.PathListSeparator))
	if len(pyPath) == 0 || pyPath[0] != filepath.Join(wantHome, "vendor") {
		t.Fatalf("PYTHONPATH = %v, want first entry %q", pyPath, filepath.Join(wantHome, "vendor"))
	}
}

func TestValidateFallbackVendorAttestationRejectsVersionMismatch(t *testing.T) {
	home := t.TempDir()
	stateRoot := filepath.Join(home, "state")
	vendorRoot := filepath.Join(stateRoot, "vendor")
	pkgRoot := filepath.Join(vendorRoot, "twinbox_core")
	if err := os.MkdirAll(pkgRoot, 0o755); err != nil {
		t.Fatalf("mkdir vendor: %v", err)
	}
	if err := os.WriteFile(filepath.Join(pkgRoot, "__init__.py"), []byte("# pkg\n"), 0o644); err != nil {
		t.Fatalf("write package: %v", err)
	}
	if err := os.WriteFile(
		filepath.Join(vendorRoot, "MANIFEST.json"),
		[]byte("{\"twinbox_version\":\"9.9.9\"}\n"),
		0o644,
	); err != nil {
		t.Fatalf("write manifest: %v", err)
	}

	cfg := fallbackCommandConfig{
		Env: map[string]string{
			"HOME":                   home,
			"TWINBOX_STATE_ROOT":     stateRoot,
			"TWINBOX_CANONICAL_ROOT": stateRoot,
		},
	}

	err := validateFallbackVendorAttestation(cfg)
	if err == nil {
		t.Fatalf("validateFallbackVendorAttestation() = nil, want error")
	}
	if !strings.Contains(err.Error(), "twinbox_version") {
		t.Fatalf("error = %v, want mention twinbox_version", err)
	}
}

func buildTwinboxCoreTarball(t *testing.T) []byte {
	t.Helper()

	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	tw := tar.NewWriter(gz)
	writeTarFile(t, tw, "twinbox_core/__init__.py", []byte("# pkg\n"))
	writeTarFile(t, tw, "twinbox_core/task_cli.py", []byte("VALUE = 42\n"))
	if err := tw.Close(); err != nil {
		t.Fatalf("close tar writer: %v", err)
	}
	if err := gz.Close(); err != nil {
		t.Fatalf("close gzip writer: %v", err)
	}
	return buf.Bytes()
}

func writeTarFile(t *testing.T, tw *tar.Writer, name string, body []byte) {
	t.Helper()

	hdr := &tar.Header{
		Name: name,
		Mode: 0o644,
		Size: int64(len(body)),
	}
	if err := tw.WriteHeader(hdr); err != nil {
		t.Fatalf("write tar header for %s: %v", name, err)
	}
	if _, err := tw.Write(body); err != nil {
		t.Fatalf("write tar body for %s: %v", name, err)
	}
}

func assertFileContains(t *testing.T, path string, want string) {
	t.Helper()

	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	if !bytes.Contains(data, []byte(want)) {
		t.Fatalf("%s = %q, want substring %q", path, string(data), want)
	}
}
