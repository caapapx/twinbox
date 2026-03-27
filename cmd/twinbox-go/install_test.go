package main

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
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
