# Verify a download

GitHub generates each ZIP from a fixed package tag. Extract it and enter the
inner WetMeat-Windows, WetMeat-Linux or WetMeat-Source folder. The outer ZIP's
name contains its version; it does not need to match an example filename in
the original setup guide.

The inner `SHA256SUMS.txt` covers the actual package files. On Linux, run:

```bash
sha256sum -c SHA256SUMS.txt
```

The Linux installer checks that manifest before copying files. The Windows CMD
installer checks the engine EXE with the native Windows `certutil` command.
Both installers preserve an existing installation instead of replacing it.

The Discord pack's parts and Join helpers reconstruct the original saved ZIPs;
its checksums apply to those reconstructed files. GitHub's outer ZIP is a
separate container and is not expected to have the original saved ZIP hash.
GitHub may also change how it compresses generated archives over time; use the
inner file checksums to verify their contents.

Stable Windows AVX2 engine SHA256:
`ba3b51c100e2f7525b61d0a3fed9ffebc587d4b596c4264974cac500dc715282`

Stable Linux AVX2 engine SHA256:
`80ef6e114018f3ee823ba6c7411ff4f6160bc8d1f72f9ced399ed3144aa9ab6b`

Stable Linux AVX-512 engine SHA256:
`53a537c92e0ecf1ba5c1170e1f0724879bad871062ffbcd47dbffa9ff343d2c2`

The packaging checks do not measure engine strength. Native Windows installer
execution remains untested; the unchanged EXE had earlier checks under Wine.
