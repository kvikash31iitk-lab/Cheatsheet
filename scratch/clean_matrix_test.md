# Logical Reasoning | Linear Arrangements & Matrix Distribution

### Cheat sheet - distilled from a 31-minute walkthrough on LRDI foundational sets

## 1. Executive Overview & CAT LRDI Strategy Framework

Logical Reasoning and Data Interpretation (LRDI) in competitive examinations such as CAT differs fundamentally from Quantitative Aptitude. While Quantitative Aptitude relies heavily on theoretical formulas and algebraic structures, LRDI relies on **structural agility**, **information layering**, and **systematic elimination**.

```
[Raw Clues]  ->  [Mathematical Frequency Constraints]  ->  [Structural Framework]  ->  [Deterministic Deductions]  ->  [Case Splitting]
```

### LRDI Exam Strategy Directives
* **Score-to-Percentile Dynamics**: Reaching high percentiles (95th to 99th+ percentile) does not require solving all sets. High performance stems from selecting the right set and executing error-free logical deductions under timed pressure.
* **Theory vs. Practice Balance**: Theory in LRDI consists of notation management and structural mapping (Matrix, Linear, Circular, Distributions). Mastery is built through repetitive representation of complex constraints.
* **Phase-Based Problem Solving**:
  1. **Framework Creation**: Define the base matrix or ordering axis before processing clues.
  2. **Direct Placement**: Input fixed structural constraints first.
  3. **Group Coupling**: Link dependent items (e.g., pairs that must always or never sit together).
  4. **Indirect Deduction**: Use frequency limits and spatial bounds to resolve non-obvious positions.

---

## 2. Problem Statement & Primary Data Layout

> [!def] Setup
> Johnny consumes ice cream across a week, operating under strict flavor selection preferences and daily consumption constraints.

### Baseline Rules & Parameters
* **Protagonist**: Johnny
* **Flavors (7 total)**: `L`, `O`, `M`, `BS`, `C`, `BC`, `S`
* **Time Horizon**: 7 consecutive days, strictly ordered from **Sunday to Saturday**.
* **Daily Allowance**: Exactly **3 ice creams per day**, each of a **different flavor** (no intraday duplicate flavors).

```
Total Weekly Ice Cream Slots = 7 days x 3 ice creams/day = 21 slots
```

> [!tip] Frequency Distribution Rule
> When N total slots are distributed equally among K distinct attributes, each attribute must appear exactly N / K times.
> Frequency per flavor = 21  slots/7  flavors = 3  times per week

```
+---------------------------------------------------------------------------------+
|                                 WEEKLY HORIZON                                  |
|  Sunday    Monday    Tuesday    Wednesday    Thursday    Friday    Saturday     |
| [ ][ ][ ] [ ][ ][ ] [ ][ ][ ]   [ ][ ][ ]   [ ][ ][ ]  [ ][ ][ ]  [ ][ ][ ]    |
+---------------------------------------------------------------------------------+
```

---

## 3. Clue Catalog & Mathematical Rules

To avoid re-reading narrative text, translate every statement into formal symbolic notation immediately upon reading.

| Clue # | Statement Summary | Symbolic / Logical Representation | Immediate Deduction Type |
|---|---|---|---|
| **C₁** | When flavor `L` is eaten, it is not eaten on the next two days. | L_t implies No  L  on  t+1, t+2 | Minimum Gap Constraint (≥ 2 days gap) |
| **C₂a** | Never ate `C` and `BC` on the same day. | C  ∩  BC = ∅ | Mutual Exclusion Pair |
| **C₂b** | Always ate `S` and `BC` on the same day. | S iff BC | Mutual Inclusion Pair |
| **C₃** | Exactly two non-consecutive days with `O` and `M` together. | Σ (O  ∩  M) = 2  days (Non-adjacent) | Frequency & Spacing Constraint |
| **C₄** | `L` is never eaten with `C`, `M`, or `BS`. | L  ∩  {C, M, BS} = ∅ | Group Elimination Constraint |
| **C₅** | All 3 `BS` consumed before the day the 3rd `O` is consumed. | Day(BS_3) < Day(O_3) | Positional Order Constraint |

---

## 4. Step-by-Step Logic Chain & Deduction Sequence

### Phase 1: Determining the Fixed Positions of Flavor L
* `L` must appear exactly **3 times** in the 7-day grid (Sunday through Saturday).
* Statement **C₁** mandates a minimum 2-day gap after every occurrence of `L`:
  Pattern:  L  ->  Blank  ->  Blank  ->  L  ->  Blank  ->  Blank  ->  L
* Total span required for 3 occurrences with 2-day gaps:
  Span = 1 + 2 + 1 + 2 + 1 = 7  days
* Because the week has exactly 7 available days (Positions 1 to 7), there is **zero positional elasticity**.

> [!def] Zero Positional Elasticity
> When the minimum required span for a constrained sequence equals the total length of the available grid, the arrangement has exactly **one valid positioning**.

Positions for  L: **Sunday (Day 1)**, **Wednesday (Day 4)**, **Saturday (Day 7)**

---

### Phase 2: Resolving L-Days (Sunday, Wednesday, Saturday)
1. **Apply Elimination (C₄)**: On days containing `L`, flavors `C`, `M`, and `BS` cannot appear.
   * Available candidate flavors for `L`-days: {L, O, M, BS, C, BC, S} minus {L, C, M, BS} = {O, BC, S}.
   * Remaining empty slots per `L`-day: **2 slots**.
2. **Apply Inclusion Pair (C₂b)**: `BC` and `S` must always appear together. They require a block of **2 slots**.
3. **Evaluate Flavor O Placement on L-Days**:
   * If `O` were placed on an `L`-day, only 1 slot would remain open.
   * Placing `O` leaves no space for the mandatory pair {BC, S}.
   * Therefore, `O` **cannot** be placed on an `L`-day.
4. **Conclusion for L-Days**:
   * The two open slots on every `L`-day must be filled by `BC` and `S`.

Composition for Sunday, Wednesday, Saturday = **{L, BC, S**}

> [!note] Intermediate State Update
> * Flavors `L`, `BC`, and `S` are now completely placed (3/3 instances each).
> * They cannot appear on any remaining open days (Monday, Tuesday, Thursday, Friday).

---

### Phase 3: Positioning Flavor BS
* Flavors remaining to be placed: `BS` (3 instances), `O` (3 instances), `M` (3 instances), `C` (3 instances).
* Candidate days open for `BS`: **Monday, Tuesday, Thursday, Friday** (4 candidate days).
* Statement **C₅** specifies: All 3 instances of `BS` must occur **before** the day of the 3rd instance of `O` (Day(BS_3) < Day(O_3)).
* **Boundary Analysis**:
  * Saturday is already fully filled ({L, BC, S}).
  * If the 3rd `BS` were consumed on Friday, the 3rd `O` would have to be on Saturday or later, which is impossible because Saturday is occupied.
  * Therefore, all 3 instances of `BS` must be completed **on or before Thursday**.
* Since there are exactly 3 candidate days up to Thursday (Monday, Tuesday, Thursday), `BS` must occupy all 3 of them.

Days with  BS: **Monday**, **Tuesday**, **Thursday**


| Day | Slot 1 | Slot 2 | Slot 3 | Status |
| :--- | :--- | :--- | :--- | :--- |
| Sunday | L | BC | S | FULLY RESOLVED |
| Monday | BS | [ ] | [ ] | 2 Slots Open ({O, M, C}) |
| Tuesday | BS | [ ] | [ ] | 2 Slots Open ({O, M, C}) |
| Wednesday | L | BC | S | FULLY RESOLVED |
| Thursday | BS | [ ] | [ ] | 2 Slots Open ({O, M, C}) |
| Friday | [ ] | [ ] | [ ] | 3 Slots Open ({O, M, C}) |
| Saturday | L | BC | S | FULLY RESOLVED |


---

### Phase 4: Resolving Friday and Thursday
1. **Friday Resolution**:
   * On Friday, all 3 slots are empty.
   * Flavors `L`, `BC`, `S`, and `BS` have reached their total capacity of 3.
   * The only available flavors left with open quotas are `O`, `M`, and `C`.
   * Thus, Friday must contain all three remaining flavors:
     Composition for Friday = **{O, M, C**}

2. **Thursday Resolution**:
   * Friday contains both `O` and `M` together.
   * Statement **C₃** dictates that `O` and `M` appear together on exactly 2 **non-consecutive** days.
   * Because Thursday is adjacent to Friday, Thursday **cannot** contain both `O` and `M` simultaneously.
   * Thursday already contains `BS`. The remaining 2 slots must come from {O, M, C}.
   * To prevent `O` and `M` from being together on Thursday, Thursday **must include `C`**, plus **either `O` or `M`** (represented as `O/M`).

Composition for Thursday = **{BS, C, O/M**}
