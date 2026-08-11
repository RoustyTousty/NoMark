# Style tells

Layer 4. No script can do this, because the signature is structural and a
regex only sees words.

## The core mistake

Most "humanizers" work from a banned-word list: replace *delve* with *explore*,
*tapestry* with *mix*, and declare victory. This does not work, and it is worth
understanding why.

What actually marks generated prose is **low variance**. Sentences cluster
around one length. Paragraphs cluster around one shape. Every list has three
items. Every section is developed to the same depth. Every claim is hedged to
the same degree. Human writing is lumpy: a nine-word sentence next to a
forty-word one, one point hammered for a page and the next dismissed in a
clause, a digression that does not quite pay off.

Swapping vocabulary leaves all of that untouched. Fix the variance and the
vocabulary largely stops mattering.

## Structural signatures

Ordered roughly by how strongly they give text away.

### Uniform sentence length

The strongest tell. Generated prose drifts to 15–25 words per sentence and
stays there. Human prose ranges from 3 to 50 in the same paragraph.

**Fix:** After a long sentence, write a short one. Three words is fine. Read
the paragraph aloud — if it has a metronomic pulse, break it.

### The rule of three, everywhere

"Fast, reliable, and secure." "Planning, execution, and review." Once is
rhetoric. In every paragraph it is a fingerprint.

**Fix:** Cut triples to two items or extend to four. Keep the ones that earn
their place; a real triple has three genuinely distinct members, not two ideas
and a synonym.

### Symmetric antithesis

"It's not just X — it's Y." "This isn't about X. It's about Y." "Not only X,
but also Y." The construction is fine. The *density* is the tell, as is the
fact that both halves are always balanced in length.

**Fix:** Keep at most one per piece. Usually the second half is the only real
content — delete the setup and state the point.

### Uniform paragraph shape

Topic sentence, two or three supporting sentences, transition. Repeated
without variation.

**Fix:** Write a one-sentence paragraph. Let another run twelve. Start one
mid-argument with "But" or "So".

### Symmetric hedging

Every claim balanced by its counterweight. "While X is powerful, it's important
to consider Y." The effect is text with no position.

**Fix:** Commit. Say the thing. Hedge where you are genuinely uncertain and
nowhere else — asymmetric confidence is what actual expertise reads like.

### Abstraction without specifics

The clearest structural signal. Generated text says "significant improvements
in efficiency". A person says "cut the nightly job from 40 minutes to 6".

**Fix:** Replace abstractions with numbers, names, dates, and cases. If a
sentence survives being made specific, keep it; if there is nothing specific to
put there, the sentence was filler.

### Total coverage

Every subtopic addressed, every caveat noted, nothing left out. Real writing
has priorities and omissions.

**Fix:** Cut a section. Leave a point underdeveloped on purpose. Real writers
run out of interest.

### The summary paragraph

"In conclusion," restating what was just said. Rare in good prose outside
academic abstracts.

**Fix:** Delete it. End on the last real point. Endings can be abrupt.

### Header and bullet reflex

Headers on everything, bullets for anything with more than two members, and
every bullet formatted as **Bold term**: explanation.

**Fix:** Prose can carry a list. Vary bullet length so they are not all one
line. Drop headers from short pieces entirely.

## Lexical signatures

Secondary, but worth a pass once the structure is fixed.

**Overused verbs and nouns:** delve, tapestry, testament, realm, landscape,
underscore, harness, foster, cultivate, embark, navigate, leverage, elevate,
unlock, unleash, spearhead, streamline, resonate, showcase.

**Inflated adjectives:** pivotal, crucial, vital, essential, robust,
comprehensive, meticulous, nuanced, multifaceted, intricate, seamless, holistic,
myriad, invaluable, transformative.

**Connective tics:** moreover, furthermore, additionally, notably, importantly,
consequently. Used where "and", "so", or nothing would do.

**Throat-clearing:** "It's worth noting that", "It's important to remember",
"When it comes to", "At its core", "In today's fast-paced world", "In the
ever-evolving landscape of", "Let's dive in", "That said".

**Set phrases:** "plays a crucial role in", "stands as a testament to", "a
treasure trove of", "navigate the complexities of", "unlock the potential of",
"in the realm of", "a game-changer".

**Fix:** Delete throat-clearing outright — it never carries content. Replace
inflated adjectives with nothing rather than a synonym; "a robust solution" is
"a solution". Prefer plain connectives.

## Punctuation and mechanics

- **Em dashes.** Currently the single most-cited tell. The signal is density,
  not presence — human writers use them. Vary rather than eliminate; removing
  every one is its own signal.
- **Curly quotes and ellipsis characters** in a plain text field mean the text
  came from somewhere else. Handled by `clean_text.py`.
- **Zero typos and perfectly parallel grammar** across a long piece is itself
  unusual. This is not a licence to insert errors deliberately — that reads as
  fake — but do not smooth out every natural roughness either.

## Doing the rewrite

1. Read the whole piece before changing anything. The signature is at the
   document level.
2. Fix structure first: sentence variance, paragraph shape, triples, hedging.
3. Then make abstractions concrete. This is where most of the improvement is.
4. Then do a lexical pass, deleting rather than substituting.
5. Read it aloud. Anything you would not say, cut.

**Preserve the author's meaning exactly.** Change how it is built, never what
it claims. If a sentence needs a specific to replace an abstraction and you do
not have one, ask the user for it rather than inventing a plausible number.
That is the one failure mode of this layer that actually matters: a rewrite
that invents facts is worse than the machine-sounding original.
