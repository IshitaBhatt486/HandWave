# Gesture recognition

```mermaid
flowchart LR
    F[Camera frame] --> MP[MediaPipe Hands<br/>21 landmarks per hand]
    MP --> HS[HandState per hand]
    HS --> FS[Finger states<br/>extended / folded]
    FS --> BI[Built-in poses]
    HS --> CU[Custom gestures<br/>nearest centroid]
    HS --> TH[Two-hand relationship]
    HS --> SW[Swipe tracker]
    HS --> PI[Pinch tracker]
    BI --> FL[Stability filter<br/>≥70% of 0.4 s, held ≥0.25 s]
    CU --> FL
    FL --> AR{Arbitration}
    TH --> AR
    PI --> AR
    SW --> AR
    AR -->|one action name per frame| AM[ActionMapper]
```

## Built-in static gestures

`GestureEngine.GESTURE_PATTERNS` (`handwave/gestures/gesture_engine.py`) maps a
per-finger extended/folded pattern (`HandLandmarkData.get_finger_states()`,
derived from joint angles, rotation-independent) to a name: Open Palm, Fist,
Thumbs Up, Thumbs Down, Peace Sign, Pointing. Thumbs Up/Down also check the
thumb's direction vector, since both share the same finger-state pattern.
`SwipeRecognizer` detects two deliberately distinct motion sources. A
**finger swipe** follows landmark 8 (the index fingertip) only while the index
finger is extended and middle/ring/pinky are folded. A **hand swipe** follows
the whole-hand landmark centroid only while all five fingers are extended
(open palm). This source is emitted in diagnostics and is not inferred from a
gesture display name. Finger swipes are vertical only; open-hand swipes can be
vertical or horizontal. Pinch (`PinchController`) uses its own geometry.

## Navigation swipes: manual test procedure

Keep the hand in view, make one decisive movement in roughly 0.1–0.7 seconds,
then release the pose before repeating. The movement must be at least about
18% of the camera frame and predominantly one axis; diagonal and slow motion
are rejected.

| Physical gesture | Default configured action |
| --- | --- |
| Extend only your index finger; move it upward | Finger Swipe Up → `Alt+Tab` (bring forward the most recently used window) |
| Hold an open palm; move the whole hand upward | Hand Swipe Up → `Win+Tab` (show Task View) |
| Extend only your index finger; move it downward | Finger Swipe Down → `Esc` (dismiss/collapse an overview) |
| Hold an open palm; move the whole hand downward | Hand Swipe Down → `Esc` (dismiss/collapse an overview) |
| Hold an open palm; move it left | Swipe Left → `Win+Ctrl+Left` (previous virtual desktop) |
| Hold an open palm; move it right | Swipe Right → `Win+Ctrl+Right` (next virtual desktop) |

All six bindings appear in Settings → Gestures & Actions and can be disabled
or rebound. If Windows rejects synthetic input, HandWave records a local
warning and safely performs no fallback action.

## Multi-hand tracking

MediaPipe is configured for up to 2 hands (`GestureEngine.MAX_HANDS`). Each
detected hand becomes an immutable `HandState`
(`handwave/gestures/hand_state.py`): landmarks, timestamp, handedness (or
`None` when MediaPipe's handedness confidence is below
`HANDEDNESS_CONFIDENCE_THRESHOLD` — treated explicitly as "uncertain," never
guessed), and a coarse `pose` property (Open Palm / Fist / Other) used only
for two-hand pose agreement. The first detected hand is always the "primary"
hand for single-hand fields, which is exactly what happened before multi-hand
support existed (max_num_hands was 1), so single-hand behavior is unchanged.

## Two-hand gestures

`TwoHandRecognizer` (`handwave/gestures/two_hand_recognizer.py`) treats a
two-hand gesture as a *relationship* between two `HandState`s — centroid
distance and its change across frames, plus pose agreement — rather than
running the single-hand classifier twice and guessing:

| Gesture | Condition |
|---|---|
| Both Palms Open | both hands' pose is Open Palm, distance stable |
| Both Fists | both hands' pose is Fist, distance stable |
| Hands Moving Apart | both Open Palm, centroid distance increasing past a threshold |
| Hands Moving Together | both Open Palm, centroid distance decreasing past a threshold |

Requiring pose agreement before motion is considered is what keeps incidental
repositioning (e.g., while doing an unrelated single-hand gesture) from being
misread as a two-hand gesture — see the false-activation tests in
`tests/test_two_hand_recognizer.py`.

## Arbitration priority

One action name is chosen per frame, in this order (implemented by
`select_action_candidate()` in `handwave/gestures/arbitration.py`):

**two-hand gesture > pinch > swipe > static gesture**

```mermaid
flowchart TD
    A{Two-hand gesture?} -->|yes| T[use it]
    A -->|no| B{Pinch active?}
    B -->|yes| P[pinch volume]
    B -->|no| C{Swipe completed?}
    C -->|yes| S[use swipe]
    C -->|no| D{Stable static pose?}
    D -->|yes| ST[use pose]
    D -->|no| N[no action]
```

This is a small, explicit policy function, not a configurable priority table.
Changing it means editing that policy, which documents the rationale
(two-hand and pinch are intentional, low-ambiguity motions;
swipe and static poses are more prone to accidental triggering while doing
something else with the hand).

## Custom gestures

`handwave/gestures/custom_gesture.py` builds a custom gesture from the same
5-value finger-extension vector the built-in patterns use
(`extension_vector()`), so built-in and custom gestures share one
representation. Recording quality control (`evaluate_sample`) rejects a
sample for: no hand detected, too much tracking loss, too short/long a
duration, inconsistent trajectory (centroid moved too much for a *static*
pose), or excessive per-finger variance. `compute_representative_gesture()`
averages accepted samples into a centroid and derives a distance tolerance;
`CustomGestureMatcher` is a nearest-centroid classifier against that
tolerance. `detect_conflicts()` compares a candidate against both built-in
prototypes and existing custom gestures. `combine_detections()` gives
built-in gestures priority — a custom gesture only fills in poses the
built-in patterns leave as "Unknown."

Gestures are recorded and tested from **Custom Gestures** on the dashboard
(`handwave/ui/custom_gestures_dialog.py`). Only static single-hand poses are
supported. The sample format (`GestureFrame`/`GestureSample`) already stores
per-frame timestamps and centroids, so motion and two-hand custom gestures
could reuse it, but nothing matches them yet.

## Record and replay

`GestureEngine.recognize_hands(hand_states)` is the single method that runs
recognition (built-in + custom + two-hand) after hand states are known —
`process()` calls it after MediaPipe extraction; `LandmarkReplayer`
(`handwave/gestures/landmark_replay.py`) calls it directly with hand states
reconstructed from a recorded `LandmarkSequence`
(`handwave/gestures/landmark_sequence.py`). Replaying a sequence therefore
runs exactly the code used live. To replay a recording
(`LandmarkRecorder` creates them):

```powershell
python scripts\replay_gesture.py path\to\sequence.json --speed 2
```

Recordings store normalized landmark data only (never camera frames), with a
`schema_version` and metadata field labeling the content as landmark data.
