# Contributing to Bad Banana

Thanks for your interest in improving Bad Banana! Bug reports, ideas and pull requests are all welcome.

## Ground rules

Bad Banana has a few deliberate constraints. Please keep them in mind before opening a pull request:

1. **One file.** The whole application, including the web page, lives in `bad_banana.py`.
2. **Standard library only.** It must run on a fresh Raspberry Pi OS install with nothing extra installed. No `pip install`, no npm, no CDNs.
3. **Python 3.7 or newer.** Avoid syntax that newer Python versions added, such as the walrus operator, `match` statements and `X | Y` type unions.
4. **Web safe.** The page is served with a strict Content Security Policy. Keep all styles and scripts inline in the template, avoid `eval` and inline event handlers, and put untrusted text into the page with `textContent` or `escapeHtml`, never raw `innerHTML`.
5. **No comments or dead code.** Use clear names instead of comments, and remove anything unused.

## Development setup

```bash
git clone https://github.com/Digim0rt4l/bad-banana.git
cd bad-banana
python3 bad_banana.py --music ~/Music --verbose
```

Then open <http://localhost:8080>. The `--verbose` flag keeps request and album art logs visible after startup.

## Before you open a pull request

```bash
python3 -m py_compile bad_banana.py
python3 -m pip install pyflakes
python3 -m pyflakes bad_banana.py
```

Please also:

- Play a few tracks in a desktop browser **and** on a phone.
- Check the browser console (F12) for errors or Content Security Policy violations.
- Test with `--no-online-art` if you changed anything to do with album art.
- Update `README.md` and `CHANGELOG.md` if you changed behaviour, commands or options.

The [CI workflow](.github/workflows/ci.yml) runs the same compile, lint and smoke tests on Python 3.7 to 3.13 for every pull request.

## Code style

- 4-space indentation in Python, JavaScript and CSS.
- Python follows PEP 8 with descriptive names.
- JavaScript uses `const` and `let`, strict mode, and double-quoted strings.
- Keep lines readable. Break long expressions over several lines rather than squeezing them onto one.

## Reporting bugs

Use the [bug report form](../../issues/new/choose). Including your Pi model, Python version, browser and the output of `--verbose` makes problems much faster to fix.

Security problems should be reported privately. See [SECURITY.md](SECURITY.md).
