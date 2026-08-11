# Limits

What NoMark cannot do. Read this before telling a user their file is clean.

## Statistical watermarks cannot be stripped

The most important limitation, and the one most often misunderstood.

Schemes like **SynthID-Text** do not insert a character. They bias the token
sampler during generation so that the output follows a secret pattern across
the whole passage. The watermark is a property of the *word choices*, spread
over hundreds of tokens. There is nothing to locate and nothing to delete.

Consequences:

- No scanner can point at it, including this one.
- Removing invisible characters does nothing to it.
- Only substantive rewriting — different words in different orders — degrades
  the signal, and degradation is gradual and unverifiable from outside.
- You cannot confirm removal, because verification needs the detector key.

**Never tell a user their text is watermark-free.** Say what is true: the
artefacts that were found have been removed.

## Detectors are unreliable in both directions

Perplexity-based detectors (GPTZero, Turnitin's AI indicator, and similar)
measure how predictable text is. They produce:

- **False positives** on human writing that is plain, formulaic, or technical.
  Documented disproportionate misclassification of non-native English writers,
  which has real consequences in academic settings.
- **False negatives** on lightly edited generated text.

A file that passes one detector may fail another, and the same file may score
differently on the same tool a month later. Treat any specific claim about
"passing" as unfounded.

## Provenance outside the file

Local cleaning does not touch:

| Where | What it holds |
|---|---|
| Google Docs / Office 365 | Full server-side revision history, keystroke timing in some cases |
| Word autosave, `.asd` files | Local recovery copies of earlier states |
| Submission platforms | Upload times, IP addresses, browser fingerprints, sometimes paste events |
| Email | Client and route in headers |
| Cloud storage | File versions, access logs |
| The recipient | Any copy already sent |

If the original has already been shared, cleaning your copy accomplishes
nothing.

## Format-specific gaps

**PDF signatures break.** Rewriting changes the bytes a signature covers. This
is inherent, not a bug.

**PDF forms and annotations** may not survive a `pypdf` rebuild. Check the
output if the file is interactive.

**Unaccepted tracked changes still contain deleted text.** NoMark anonymises
authorship; it does not accept or reject revisions. Deleted content remains in
the file until the user resolves the changes in Word.

**Embedded objects are not inspected.** A chart linked to a spreadsheet, an
embedded font, or an OLE object can carry its own metadata. NoMark removes
thumbnails but does not recurse into embedded binaries.

**Images inside documents keep their EXIF.** NoMark v1 handles the document
container, not the media inside it. Use `exiftool` for images.

**Scanned PDFs are images.** There is no text layer to clean, and the scan
itself may carry printer or scanner artefacts.

## Things that reintroduce metadata

Order of operations matters more than people expect:

- Opening and re-saving a cleaned `.docx` in Word **puts the properties back**,
  populated from the current user's Office profile. Clean last, immediately
  before sending.
- Exporting to PDF from a dirty source carries the source's metadata forward.
  Clean the source first, then export.
- Copying cleaned text back through a rich-text editor can reintroduce curly
  quotes and non-breaking spaces.
- Pasting into Google Docs, then downloading, produces a file with Google's
  metadata and a fresh server-side history.

## Cleaning is itself detectable

Worth being honest about. A document with all timestamps at `1980-01-01`, no
`Application` field, and no rsid table is obviously scrubbed. Absence of
metadata is not the same as innocuous metadata — it is a signal that a tool was
run.

For most purposes (privacy before publication, removing a former employer's
name) that is fine and even expected. If a user's goal specifically requires the
file to look untouched, tell them this tool does not provide that.

## Scope note

NoMark deliberately does not implement attacks on cryptographic content
provenance — C2PA manifests and similar signed provenance chains for images and
video. Those systems exist to let people verify that a photograph is what it
claims to be, and defeating them serves manipulated-media use cases rather than
the privacy and cleanup cases this tool is built for.

Document metadata and text-layer artefacts are a different matter: they are
unsigned, they leak information the author never chose to publish, and stripping
them is standard pre-publication hygiene.
