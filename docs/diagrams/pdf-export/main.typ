// Production diagram export. Global theme remains owned by report-theme.typ.
#import "report-theme.typ": report-accent, report-theme

#show: report-theme.with(
  title: "Pre-Acceptance Baseline-Import Lifecycle",
  author: "Manus AI",
  rhythm: "report",
  running-header: false,
)

#set page(
  width: 17in,
  height: 17in,
  margin: (top: 0.38in, bottom: 0.32in, x: 0.42in),
  header: none,
  footer: none,
)

#set par(first-line-indent: 0pt)

#align(center)[
  #text(size: 17pt, weight: "bold", fill: report-accent)[
    Pre-Acceptance Baseline-Import Lifecycle
  ]
  #v(0.08in)
  #text(size: 8.5pt)[
    Logical two-phase workflow: immutable staging and validation, then explicit human apply in one tenant-scoped transaction.
  ]
]

#v(0.12in)

#align(center)[
  #image("baseline-import-lifecycle.png", width: 15.3in)
]

#v(0.06in)

#align(center)[
  #text(size: 7.5pt, fill: luma(45))[Editable source: `docs/diagrams/baseline-import-lifecycle.mmd`. This is a logical two-phase import lifecycle, not a distributed database two-phase-commit protocol.]
]
