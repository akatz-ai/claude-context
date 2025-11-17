# Publishing to PyPI

This project uses GitHub Actions to automatically publish to PyPI using **Trusted Publishing** (no API tokens required).

## Setup (One-time)

### 1. Create the Package on PyPI

First, you need to register the package name on PyPI:

1. Go to [https://pypi.org](https://pypi.org) and log in
2. Click "Publishing" in the left sidebar
3. Click "Add a new publisher"
4. Fill in the form:
   - **PyPI Project Name**: `claude-context`
   - **Owner**: `<your-github-username>` (or organization)
   - **Repository name**: `claude-context` (or whatever your repo is named)
   - **Workflow name**: `publish.yml`
   - **Environment name**: (leave blank)
5. Click "Add"

**Note**: You don't need to create an API token or set up any secrets!

### 2. Push to GitHub

Make sure your code is pushed to GitHub:

```bash
# If you haven't already created a GitHub repo
gh repo create claude-context --public --source=. --remote=origin

# Push your code
git push -u origin main
```

## Publishing

There are two ways to publish:

### Option 1: Automatic (on push to main)

Every time you push to the `main` branch, the workflow will automatically:
1. Build the package
2. Publish to PyPI (if trusted publishing is set up)

```bash
# Update version in pyproject.toml first
# Then commit and push
git add pyproject.toml
git commit -m "Bump version to 0.2.0"
git push origin main
```

### Option 2: Manual Trigger

You can manually trigger the workflow from GitHub:

1. Go to your repository on GitHub
2. Click "Actions" tab
3. Click "Publish to PyPI" workflow
4. Click "Run workflow" button
5. Select the branch and click "Run workflow"

## Version Management

Before publishing, always update the version in `pyproject.toml`:

```toml
[project]
name = "claude-context"
version = "0.2.0"  # ← Update this
```

## Workflow Details

The workflow (`.github/workflows/publish.yml`):
- Triggers on push to `main` or manual dispatch
- Uses `uv` to build the package
- Uses PyPA's trusted publishing action (no tokens needed)
- Runs on Ubuntu with Python 3.9+

## Troubleshooting

**"Workflow failed: PyPI publishing failed"**
- Make sure you've set up trusted publishing on PyPI (see Setup above)
- Check that the repository name and workflow name match exactly

**"Package already exists"**
- You forgot to bump the version in `pyproject.toml`
- PyPI doesn't allow re-uploading the same version

**"Invalid credentials"**
- Trusted publishing might not be set up correctly
- Double-check the PyPI publisher configuration matches your repo

## Testing Locally

Before publishing, test the build locally:

```bash
# Build the package
uv build

# Check the dist/ directory
ls -lh dist/

# Test installation from the built wheel
uv tool install dist/claude_context-0.1.0-py3-none-any.whl

# Or test with PyPI test server (optional)
# You'll need to set up trusted publishing on test.pypi.org too
```

## First Time Publishing Checklist

- [ ] Updated version in `pyproject.toml`
- [ ] Set up trusted publishing on PyPI
- [ ] Pushed code to GitHub
- [ ] Verified package name `claude-context` is available on PyPI
- [ ] Tested build locally with `uv build`
- [ ] Ready to trigger the workflow!
