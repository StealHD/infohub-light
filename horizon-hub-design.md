# HorizonHub Product Design Document

## Positioning

**One-sentence positioning**: The information source marketplace for the Horizon ecosystem—driven by real community usage data for discovery, recommendation, and quality assessment.

**Difference from Competitors**:

| Product | What it does | What it doesn't do |
|---|---|---|
| RSSHub | Turns websites without RSS into RSS (Pipe) | No quality assessment, no recommendations |
| Feedly | RSS Reader with discovery features | No AI filtering, no personalized recommendations |
| HN / Reddit | Community-driven content aggregation | Fixed sources, user cannot customize |
| **HorizonHub** | **Data-driven source recommendation & quality assessment** | **No content hosting, not a reader** |

**Core Moat**: The daily operation of every Horizon user generates quality data for information sources (AI scores, signal-to-noise ratio, output frequency). When aggregated in the Hub, this data forms a **dynamic quality profile** that no static recommendation list can provide.

---

## System Architecture

```
┌──────────────────────────────────────────────────┐
│                    User Local                    │
│                                                  │
│  horizon-wizard (TUI)       Horizon CLI          │
│  ┌────────────────┐         ┌────────────────┐   │
│  │ Browse/Search  │         │ Fetch -> AI    │   │
│  │ Add/Remove     │──Write─▶│ Score ->       │   │
│  │ Recommend      │         │ Gen Summary    │   │
│  └───────┬────────┘         └───────┬────────┘   │
│          │                          │            │
└──────────┼──────────────────────────┼────────────┘
           │ Report Ops Events        │ Report Quality Data
           ▼                          ▼
┌──────────────────────────────────────────────────┐
│                 HorizonHub Server                │
│                                                  │
│  ┌───────────┐  ┌─────────────┐  ┌────────────┐  │
│  │ Source DB │  │ Rank Engine │  │ Recommender│  │
│  └───────────┘  └─────────────┘  └────────────┘  │
│                        │                         │
│               ┌────────▼────────┐                │
│               │   Hub Web UI    │                │
│               │ (Market / Rank) │                │
│               └─────────────────┘                │
└──────────────────────────────────────────────────┘
```

Two core components:
- **Hub Server**: Data center + Web frontend, receiving reports, storing statistics, providing APIs and web pages.
- **Local Client (horizon-wizard)**: The sole entry point for users to manage information sources; every operation naturally generates data.

---

## Feature List

### Source Market (Browse)

The core interface users see when opening the Hub website.

**Page Structure**:

- **Top Dashboard**: A row of statistics cards.
  - Total Sources | Field Categories | Contributors | Active Users

- **Source Card Waterfall**: Each source has a card.
  - Source Name + Type Tags (RSS / Reddit / GitHub / Telegram / Twitter)
  - Color-coded Field Tags (AI Purple, Systems Blue, Security Red...)
  - One-sentence Bio (CN/EN)
  - Key Metrics: Users · AI Avg Score · Signal-to-Noise Ratio
  - Contributor Avatars
  - Badges: 🔥 Hot / ✨ New / ⚠️ Quality Dropped

- **Filtering and Sorting**:
  - Filter by field / language / type
  - Sort by Popularity (Users) / Quality (AI Avg) / SNR / Latest Added
  - Keyword Search

### Source Profile

The detail page for each source, showing a complete data-driven profile.

**Included Data**:

| Metric | Description | Data Source |
|---|---|---|
| Active Users | Number of users using this source in the past 30 days | Telemetry |
| AI Avg Score | Average AI score of content produced by this source | Telemetry |
| SNR | Percentage of items passing AI filtering vs. total fetched | Telemetry |
| Avg Daily Output| Average number of items fetched per day | Telemetry |
| Score Trend | Line chart of AI average scores over the last 30 days | Telemetry Aggregation |
| User Trend | Changes in active users over the last 30 days | Telemetry Aggregation |
| Contributor | Who submitted this source | User submission records |
| Date Added | When it was added to the Hub | Submission records |

### User Submission (Contribute)

**Submission Process**:

```
User (Hub Web or Local Client)
  → GitHub OAuth Login
  → Fill info: Name, URL, Type, Category, Language, Bio
  → Submit

Hub Server
  → Automatically fetch last 10 items from source
  → AI quality assessment (Avg score, SNR)
  → Quality OK → Auto-online, Status: ✅ Online
  → Quality Poor → Mark pending, notify maintainer for manual review
```

**Channels**:
- Hub Web Form (most intuitive)
- Local Client Submission (one-click via `horizon-wizard`)

### Intelligent Recommendation (Recommend)

**Scenarios**:

1. **New User Cold Start**: Enter interest keywords ("AI", "Linux Kernel") to recommend the best source combination.
2. **Complementary Recommendation**: Analyze existing config to recommend sources with complementary coverage and flag high-overlap sources.
3. **Collaborative Filtering** (post-scale): "Users with similar tastes also read..."

**Input for Rec Algorithm**:
- Source field tags
- Content overlap between sources (calculated via deduplication data)
- Usage patterns of user cohorts

### One-click Export (Export)

After users select sources on the Hub website:

- Generate `config.json` snippet → Copy to clipboard
- Download full config file
- Generate `horizon-wizard` command → One-click import via terminal

### Contributor System (Community)

**Contributor Leaderboard**:
- Ranked by number of sources contributed.
- Displays GitHub avatar + link + contribution count.

**Contributor Homepage**:
- Sources I submitted.
- How many people use my sources in total.
- Average quality score of my sources.

**Badge System**:

| Badge | Condition |
|---|---|
| 🌱 First Contribution | Submit the first source |
| 🌟 Quality Contributor| Contributed sources have Avg Score ≥ 7.0 |
| 🔥 Popular Contributor| A single source used by ≥ 50 people |
| 👑 Core Contributor | Contributed ≥ 10 sources |

### Source Health Monitoring

**Automatic Decay Detection** (Option A — Passive):

Hub server continuously tracks active user trends for each source. If usage drops continuously (e.g., >30% drop within 30 days), auto-mark with a ⚠️ warning.

**User Feedback Collection** (Option B — Active):

When a user deletes or disables a source via `horizon-wizard`, a popup asks for optional feedback:

```
You removed "QbitAI", can you tell us why? (Optional, Enter to skip)
1. Quality dropped
2. Too much overlap with other sources
3. Low update frequency / defunct
4. Doesn't match my interests
>
```

Reported to the Hub, integrated with decay data for comprehensive judgment.

---

## Distributed Agent Operating System

### Analogy

If the Horizon ecosystem is viewed as a **Distributed Agent Operating System**.

A single Horizon instance is like a "standalone machine" managing one user's information flow. HorizonHub acts as the **Control Plane** that coordinates all users' Agents into a whole, allowing decentralized individual judgments to converge into collective intelligence.

### Why "Emergence"?

Each Agent runs independently and is unaware of others, but:
- **Diversity**: Different users subscribe to sources in different fields, naturally providing diverse perspectives.
- **Independence**: Each Agent's AI scoring is unaffected by other users.
- **Aggregation**: The Hub aggregates all scores to form a global quality signal more accurate than any single Agent.

This is not designed intelligence, but rather consensus **emerging** from a large number of independent judgments—mathematically aligned with the Condorcet Jury Theorem.

---
