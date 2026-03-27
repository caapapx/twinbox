package main

import (
	"archive/tar"
	"compress/gzip"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

func runInstall(args []string) int {
	fs := flag.NewFlagSet("install", flag.ExitOnError)
	stateRoot := fs.String("state-root", "", "State root (default $TWINBOX_STATE_ROOT or $HOME/.twinbox)")
	archivePath := fs.String("archive", "", "Path to .tar.gz containing top-level twinbox_core/")
	_ = fs.Parse(args)
	if *archivePath == "" {
		fmt.Fprintln(os.Stderr, "twinbox-go install: --archive <path> is required")
		return 2
	}
	root := strings.TrimSpace(*stateRoot)
	if root == "" {
		root = os.Getenv("TWINBOX_STATE_ROOT")
	}
	if root == "" {
		root = filepath.Join(os.Getenv("HOME"), ".twinbox")
	}
	root = filepath.Clean(root)
	vendorDir := filepath.Join(root, "vendor")
	destPkg := filepath.Join(vendorDir, "twinbox_core")
	if err := os.MkdirAll(vendorDir, 0o700); err != nil {
		fmt.Fprintf(os.Stderr, "twinbox-go install: mkdir vendor: %v\n", err)
		return 1
	}
	if err := os.RemoveAll(destPkg); err != nil {
		fmt.Fprintf(os.Stderr, "twinbox-go install: clear dest: %v\n", err)
		return 1
	}
	if err := extractTwinboxCoreTarball(*archivePath, vendorDir); err != nil {
		fmt.Fprintf(os.Stderr, "twinbox-go install: %v\n", err)
		return 1
	}
	fmt.Printf("extracted twinbox_core -> %s\n", destPkg)
	return 0
}

func extractTwinboxCoreTarball(path string, vendorDir string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	gz, err := gzip.NewReader(f)
	if err != nil {
		return err
	}
	defer gz.Close()
	tr := tar.NewReader(gz)
	found := false
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
		name := filepath.Clean(hdr.Name)
		if name == "." || name == ".." || strings.HasPrefix(name, ".."+string(os.PathSeparator)) {
			continue
		}
		if !strings.HasPrefix(name, "twinbox_core") {
			continue
		}
		found = true
		target := filepath.Join(vendorDir, name)
		switch hdr.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, 0o700); err != nil {
				return err
			}
		case tar.TypeReg:
			if err := os.MkdirAll(filepath.Dir(target), 0o700); err != nil {
				return err
			}
			out, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, os.FileMode(hdr.Mode&0o777))
			if err != nil {
				return err
			}
			if _, err := io.Copy(out, tr); err != nil {
				out.Close()
				return err
			}
			out.Close()
		}
	}
	if !found {
		return fmt.Errorf("archive has no twinbox_core/ entries")
	}
	return nil
}
