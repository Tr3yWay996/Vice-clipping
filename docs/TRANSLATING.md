# Translating Vice

Vice's interface lives in one JSON file per language. Adding a language means
filling in a copy of the English one and opening a pull request. You do not
need to finish it, and you do not need to know any TypeScript.

Everything on this page needs Node installed, which you already have if you can
run `npm`. Nobody installing Vice needs Node: the built interface is committed
to the repository.

## Four steps

**1. Start the file.**

```bash
git clone https://github.com/splitshotz/Vice
cd Vice
npm install
npm run i18n:new -- pt-BR
```

Use your own language tag in place of `pt-BR`: `fr`, `de`, `pl`, `es-MX`. That
creates `ui-src/locales/pt-BR.json` as a copy of the English one, with the
English text still in place as the values, and adds it to
`ui-src/locales/index.ts`.

**2. Translate the values. Leave the keys alone.**

```json
"clips": {
  "saveClip": "Save clip",        ← change this side
  "newPlaylist": "New playlist"
}
```

Three things to keep:

- **`{name}` placeholders.** `"Added to {playlist}"` becomes
  `"Ajouté à {playlist}"`. The word inside the braces is a slot Vice fills in,
  so it has to survive untouched. You can move it anywhere in the sentence.
- **Plural forms.** A value that is an object rather than a string is a plural:

  ```json
  "countClips": {"one": "{count} clip", "other": "{count} clips"}
  ```

  English needs two forms. Your language may need one, or six. Use the
  categories it actually has (`zero`, `one`, `two`, `few`, `many`, `other`) and
  leave out the ones it does not. `other` is required. If you are not sure which
  your language uses, the CLDR plural rules chart has the answer:
  https://cldr.unicode.org/index/cldr-spec/plural-rules
- **Your language's own name.** In `ui-src/locales/index.ts`, set the label to
  the way you would write it yourself: `'Português (Brasil)'`, not
  `'Portuguese'`.

**3. Check your work.**

```bash
npm run i18n:check
```

It prints how much of each language is done and what is still English. It also
catches a key you renamed by accident, which is the one mistake that breaks
something.

To see it running, build the interface and restart Vice:

```bash
npm run build
systemctl --user restart vice.service
```

Vice picks your system language automatically. To look at another one, use the
Language picker in Settings under Appearance.

**4. Open a pull request.**

Commit `ui-src/locales/<your-locale>.json`, `ui-src/locales/index.ts` and the
rebuilt `vice/ui/scripts/app.js`. The pull request keeps your name on the work,
and you get credited by handle in the release notes and in the README.

## Things worth knowing

**A half-finished translation is fine.** Anything you have not translated falls
back to English, key by key. Send 50 strings now and the rest later, or never.
Nothing breaks either way.

**Only the interface is translated.** Log lines, `vice doctor` output and error
messages from the daemon stay in English, because those get pasted into bug
reports and have to be readable by whoever is answering.

**English is the source.** When a string changes in English, `npm run i18n:check`
will show your language as having gone stale rather than silently drifting. A
follow-up pull request with just those strings is welcome and takes a minute.

**Long words.** German and Polish run about 30% longer than English. If a label
overflows a row, say so in the pull request rather than shortening the
translation into something wrong: the layout is the thing to fix.

## Required for every contributor

Every future feature or modification that introduces user-visible text must
integrate with the existing localization system and update the relevant
translations. This applies to controls, hints, errors, empty states, queue
statuses, accessibility labels and interpolated statistics. Use `t` / `tNode`,
keep placeholder names consistent, and provide natural translations in English,
French, German and Brazilian Portuguese for added or changed copy. Use the
selected app locale for number, percentage, duration and count formatting.

`npm run i18n:check` is required in CI. It rejects unknown localization keys,
new missing translations, mismatched placeholders, missing plural fallbacks and
hard-coded user-facing prose. Test fixtures and developer diagnostics are not
user interface copy. `tools/i18n-legacy-missing.json` records only the pre-existing
upstream translation backlog; do not expand it to bypass a check. Existing gaps
may still fall back to English while they are translated, but new features may
not create additional gaps.
