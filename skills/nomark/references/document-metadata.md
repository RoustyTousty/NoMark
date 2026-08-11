# Document metadata

Field maps per format. Most tools stop at the author name; the identifying
information is usually elsewhere.

## OOXML — .docx .xlsx .pptx

A zip archive of XML parts. Each part leaks separately.

### docProps/core.xml

| Field | Contains |
|---|---|
| `dc:creator` | Original author |
| `cp:lastModifiedBy` | Last person to save — often a *different* name |
| `cp:revision` | Save count; a proxy for how long the document took |
| `dcterms:created` / `dcterms:modified` | Authoring timestamps |
| `cp:lastPrinted` | Print time |
| `cp:keywords`, `dc:description`, `cp:category` | Free text, frequently stale |

Removed: identity fields. Normalised to `1980-01-01T00:00:00Z`: dates.
Kept unless `--strip-all`: `dc:title`, `dc:subject`, which are usually content.

### docProps/app.xml

`Application` and `AppVersion` identify the exact build that wrote the file.
`Company` comes from the Office installation and is often an organisation the
author forgot they were associated with. `Template` reveals `Normal.dotm` or a
corporate template path. `TotalTime` is cumulative editing minutes.

All removed. Statistics (`Pages`, `Words`) are kept — they are derivable from
the content anyway.

### docProps/custom.xml

Custom properties. DMS systems, redaction tools, and templates write matter
IDs, client codes, and classification labels here. Removed entirely.

### word/settings.xml — rsids

**The part most tools miss.** Word assigns a Revision Save ID to every editing
session and stamps it on every run and paragraph touched in that session.

```xml
<w:rsids>
  <w:rsidRoot w:val="00A12B34"/>
  <w:rsid w:val="00A12B34"/>
  <w:rsid w:val="00B56C78"/>
</w:rsids>
```

Consequences:

- The count of rsids reveals how many sessions produced the document.
- Two documents sharing an `rsidRoot` came from the same original.
- Per-run rsids reconstruct *which sentences were written when* — including
  paragraphs pasted in from somewhere else.

That last property is why rsids are used in plagiarism and provenance analysis.
NoMark removes the `w:rsids` table and every `w:rsidR`, `w:rsidRPr`,
`w:rsidRDefault`, `w:rsidP`, `w:rsidTr`, `w:rsidDel`, and `w:rsidSect`
attribute throughout the package.

Also removed: `w15:docId` / `w14:docId`, a GUID that persists across
save-as and identifies copies as siblings.

### word/document.xml — paragraph GUIDs

`w14:paraId` and `w14:textId` are durable per-paragraph identifiers that
survive editing and copying. Two documents sharing paragraph IDs share
ancestry. Removed.

### Tracked changes and comments

`w:ins` and `w:del` carry `w:author` and `w:date`. `word/comments.xml` carries
comment authors and times. `word/people.xml` is a registry of everyone who
commented, including their email in some versions.

NoMark rewrites authorship attributes to `Author`, normalises dates, and drops
`word/people.xml`. Note that this anonymises tracked changes — it does not
accept them. **Unaccepted deletions still contain the deleted text.** If the
user needs that gone, they must accept or reject changes in Word first.

### docProps/thumbnail.*

An embedded preview image of the first page, present in files saved with
"Save Thumbnail" on. It survives even if the document body is later rewritten,
so it can show content that is no longer in the file. Removed.

### Zip layer

Every entry carries a modification timestamp and a host-OS byte. Timestamps
reconstruct the authoring session; `create_system=3` says the file was written
on a Unix-like host, which distinguishes LibreOffice on Linux from Word on
Windows regardless of what `app.xml` claims.

NoMark rebuilds the archive with all timestamps at `1980-01-01` and
`create_system=0`. Entry order is preserved, which matters for ODF and EPUB
where `mimetype` must come first and uncompressed.

## ODF — .odt .ods .odp

`meta.xml` holds:

| Field | Contains |
|---|---|
| `meta:generator` | Exact build string, e.g. `LibreOffice/7.5.2.1$Linux` |
| `meta:initial-creator`, `dc:creator` | Author names |
| `meta:creation-date`, `dc:date` | Timestamps |
| `meta:editing-cycles` | Save count |
| `meta:editing-duration` | Total time spent, as an ISO 8601 duration |
| `meta:document-statistic` | Word, page, and character counts |
| `meta:user-defined` | Arbitrary custom fields |

`meta:generator` is more specific than the OOXML equivalent — it frequently
pins the operating system and patch level.

## EPUB

`content.opf` carries `dc:creator`, `dc:contributor`, `dc:publisher`,
`dc:date`, and `<meta name="generator">`. Conversion tools write themselves
into `dc:contributor`, so a book converted with Calibre says so.

## PDF

Three separate locations, and cleaning one does not clean the others.

**Info dictionary** — `/Producer`, `/Creator`, `/Author`, `/Title`, `/Subject`,
`/Keywords`, `/CreationDate`, `/ModDate`. `/Creator` is the application that
authored the source document and `/Producer` is the library that wrote the PDF;
together they fingerprint a toolchain closely.

**XMP packet** — an embedded RDF/XML block that mirrors the Info dictionary and
adds `xmpMM:DocumentID`, `xmpMM:InstanceID`, and `xmpMM:History`. The history
array can list every prior edit with tool names and timestamps. Because it
duplicates Info, stripping only the Info dictionary leaves everything intact.

**`/ID` trailer** — a pair of file identifiers. The first is stable across
revisions of the same document, so it links a "clean" copy back to its source.

NoMark reports all three with `--inspect`. Rewriting needs `pypdf`
(`pip install pypdf`).

### PDF caveats

- Rewriting rebuilds the file. Interactive forms, signatures, and some
  annotations may not survive. Signatures **will** break — that is inherent,
  since the signature covers the bytes being changed.
- A PDF exported from Word inherits Word's metadata. Clean the `.docx` first,
  then export, rather than cleaning the PDF afterwards.
- Text in a PDF still carries every layer-1 and layer-2 artefact. Metadata
  stripping does not touch the text layer.

## Not covered by any local tool

Worth saying out loud to users, because it is where the actual exposure usually
is:

- **Google Docs and Office 365 version history** lives server-side. Downloading
  a clean copy does not remove it.
- **Word autosave and recovery files** persist locally.
- **Submission platforms** log upload times, IPs, and often browser fingerprints
  independently of the file.
- **Email headers** identify the sending client and route.
- **The recipient may already hold the original.** Cleaning a file you have
  already sent achieves nothing.
