# Fabric Tasks toolbar responsive QA

Base URL: http://localhost:3101
Company: DeployFaith (DF)
Generated: 2026-07-10T03:44:57.103Z

Kanban-projected API sample:
- DF-653: Fix Agency provider health guard gaps found by QA validation
- DF-654: Fix Agency provider health guard gaps found by QA validation
- DF-656: Post-incident verification: dispatch wake fix (00da38e)
- DF-436: Fix Agency provider failure classifier integration in pool wake preflight
- DF-655: Post-incident verification: dispatch wake fix (00da38e)

| Viewport | Result | No overlap | No horizontal scroll | Touch targets | Primary actions | Secondary controls | Search/filter/sort/view/refresh | Kanban tasks | Task-limit warning | Dark contrast | Screenshots |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 320px | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | warning visible and readable | PASS (oklch(0.145 0 0) / oklch(0.985 0 0)) | /home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/320-issues-dark.png; /home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/320-issues-board-dark.png |
| 360px | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | warning visible and readable | PASS (oklch(0.145 0 0) / oklch(0.985 0 0)) | /home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/360-issues-dark.png; /home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/360-issues-board-dark.png |
| 390px | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | warning visible and readable | PASS (oklch(0.145 0 0) / oklch(0.985 0 0)) | /home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/390-issues-dark.png; /home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/390-issues-board-dark.png |
| 430px | PASS | PASS | PASS | PASS | PASS | PASS | PASS | PASS | warning visible and readable | PASS (oklch(0.145 0 0) / oklch(0.985 0 0)) | /home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/430-issues-dark.png; /home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/430-issues-board-dark.png |
| 768px | PASS | PASS | PASS | N/A desktop compact controls | PASS | PASS | PASS | PASS | warning visible and readable | PASS (oklch(0.145 0 0) / oklch(0.985 0 0)) | /home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/768-tablet-issues-dark.png; /home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/768-tablet-issues-board-dark.png |
| 1280px | PASS | PASS | PASS | N/A desktop compact controls | PASS | PASS | PASS | PASS | warning visible and readable | PASS (oklch(0.145 0 0) / oklch(0.985 0 0)) | /home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/1280-desktop-issues-dark.png; /home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/1280-desktop-issues-board-dark.png |

Failures:
- None found.

Raw JSON:
```json
{
  "baseUrl": "http://localhost:3101",
  "companyId": "ca8ff0e4-1e5e-442d-ac79-dfe42ecf1ea1",
  "kanbanProjectedSample": [
    "DF-653: Fix Agency provider health guard gaps found by QA validation",
    "DF-654: Fix Agency provider health guard gaps found by QA validation",
    "DF-656: Post-incident verification: dispatch wake fix (00da38e)",
    "DF-436: Fix Agency provider failure classifier integration in pool wake preflight",
    "DF-655: Post-incident verification: dispatch wake fix (00da38e)"
  ],
  "results": [
    {
      "viewport": {
        "name": "320",
        "width": 320,
        "height": 760
      },
      "mobile": true,
      "url": "http://localhost:3101/DF/issues",
      "screenshots": {
        "list": "/home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/320-issues-dark.png",
        "board": "/home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/320-issues-board-dark.png"
      },
      "noOverlap": true,
      "overlaps": [],
      "noHorizontalScroll": true,
      "horizontalOverflowPx": {
        "list": 0,
        "board": 0
      },
      "touchTargetsOk": true,
      "smallTargets": [],
      "primaryActionsObvious": true,
      "secondaryReachable": true,
      "controls": {
        "searchWorks": true,
        "filterReachable": true,
        "boardVisible": true,
        "secondaryControls": {
          "refresh": true,
          "board": true,
          "list": true,
          "sort": true,
          "groupOrColumns": true
        }
      },
      "kanbanProjectedVisible": true,
      "taskLimitWarningReadable": true,
      "taskLimitWarningNote": "warning visible and readable",
      "darkTheme": true,
      "colors": {
        "bg": "oklch(0.145 0 0)",
        "fg": "oklch(0.985 0 0)"
      }
    },
    {
      "viewport": {
        "name": "360",
        "width": 360,
        "height": 760
      },
      "mobile": true,
      "url": "http://localhost:3101/DF/issues",
      "screenshots": {
        "list": "/home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/360-issues-dark.png",
        "board": "/home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/360-issues-board-dark.png"
      },
      "noOverlap": true,
      "overlaps": [],
      "noHorizontalScroll": true,
      "horizontalOverflowPx": {
        "list": 0,
        "board": 0
      },
      "touchTargetsOk": true,
      "smallTargets": [],
      "primaryActionsObvious": true,
      "secondaryReachable": true,
      "controls": {
        "searchWorks": true,
        "filterReachable": true,
        "boardVisible": true,
        "secondaryControls": {
          "refresh": true,
          "board": true,
          "list": true,
          "sort": true,
          "groupOrColumns": true
        }
      },
      "kanbanProjectedVisible": true,
      "taskLimitWarningReadable": true,
      "taskLimitWarningNote": "warning visible and readable",
      "darkTheme": true,
      "colors": {
        "bg": "oklch(0.145 0 0)",
        "fg": "oklch(0.985 0 0)"
      }
    },
    {
      "viewport": {
        "name": "390",
        "width": 390,
        "height": 844
      },
      "mobile": true,
      "url": "http://localhost:3101/DF/issues",
      "screenshots": {
        "list": "/home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/390-issues-dark.png",
        "board": "/home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/390-issues-board-dark.png"
      },
      "noOverlap": true,
      "overlaps": [],
      "noHorizontalScroll": true,
      "horizontalOverflowPx": {
        "list": 0,
        "board": 0
      },
      "touchTargetsOk": true,
      "smallTargets": [],
      "primaryActionsObvious": true,
      "secondaryReachable": true,
      "controls": {
        "searchWorks": true,
        "filterReachable": true,
        "boardVisible": true,
        "secondaryControls": {
          "refresh": true,
          "board": true,
          "list": true,
          "sort": true,
          "groupOrColumns": true
        }
      },
      "kanbanProjectedVisible": true,
      "taskLimitWarningReadable": true,
      "taskLimitWarningNote": "warning visible and readable",
      "darkTheme": true,
      "colors": {
        "bg": "oklch(0.145 0 0)",
        "fg": "oklch(0.985 0 0)"
      }
    },
    {
      "viewport": {
        "name": "430",
        "width": 430,
        "height": 932
      },
      "mobile": true,
      "url": "http://localhost:3101/DF/issues",
      "screenshots": {
        "list": "/home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/430-issues-dark.png",
        "board": "/home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/430-issues-board-dark.png"
      },
      "noOverlap": true,
      "overlaps": [],
      "noHorizontalScroll": true,
      "horizontalOverflowPx": {
        "list": 0,
        "board": 0
      },
      "touchTargetsOk": true,
      "smallTargets": [],
      "primaryActionsObvious": true,
      "secondaryReachable": true,
      "controls": {
        "searchWorks": true,
        "filterReachable": true,
        "boardVisible": true,
        "secondaryControls": {
          "refresh": true,
          "board": true,
          "list": true,
          "sort": true,
          "groupOrColumns": true
        }
      },
      "kanbanProjectedVisible": true,
      "taskLimitWarningReadable": true,
      "taskLimitWarningNote": "warning visible and readable",
      "darkTheme": true,
      "colors": {
        "bg": "oklch(0.145 0 0)",
        "fg": "oklch(0.985 0 0)"
      }
    },
    {
      "viewport": {
        "name": "768-tablet",
        "width": 768,
        "height": 1024
      },
      "mobile": false,
      "url": "http://localhost:3101/DF/issues",
      "screenshots": {
        "list": "/home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/768-tablet-issues-dark.png",
        "board": "/home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/768-tablet-issues-board-dark.png"
      },
      "noOverlap": true,
      "overlaps": [],
      "noHorizontalScroll": true,
      "horizontalOverflowPx": {
        "list": 0,
        "board": 0
      },
      "touchTargetsOk": true,
      "smallTargets": [],
      "primaryActionsObvious": true,
      "secondaryReachable": true,
      "controls": {
        "searchWorks": true,
        "filterReachable": true,
        "boardVisible": true,
        "secondaryControls": {
          "refresh": true,
          "board": true,
          "list": true,
          "sort": true,
          "groupOrColumns": true
        }
      },
      "kanbanProjectedVisible": true,
      "taskLimitWarningReadable": true,
      "taskLimitWarningNote": "warning visible and readable",
      "darkTheme": true,
      "colors": {
        "bg": "oklch(0.145 0 0)",
        "fg": "oklch(0.985 0 0)"
      }
    },
    {
      "viewport": {
        "name": "1280-desktop",
        "width": 1280,
        "height": 900
      },
      "mobile": false,
      "url": "http://localhost:3101/DF/issues",
      "screenshots": {
        "list": "/home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/1280-desktop-issues-dark.png",
        "board": "/home/dadmin/repos/Hermes_Agency/apps/fabric/qa-artifacts/fabric-mobile-toolbar-qa/1280-desktop-issues-board-dark.png"
      },
      "noOverlap": true,
      "overlaps": [],
      "noHorizontalScroll": true,
      "horizontalOverflowPx": {
        "list": 0,
        "board": 0
      },
      "touchTargetsOk": true,
      "smallTargets": [],
      "primaryActionsObvious": true,
      "secondaryReachable": true,
      "controls": {
        "searchWorks": true,
        "filterReachable": true,
        "boardVisible": true,
        "secondaryControls": {
          "refresh": true,
          "board": true,
          "list": true,
          "sort": true,
          "groupOrColumns": true
        }
      },
      "kanbanProjectedVisible": true,
      "taskLimitWarningReadable": true,
      "taskLimitWarningNote": "warning visible and readable",
      "darkTheme": true,
      "colors": {
        "bg": "oklch(0.145 0 0)",
        "fg": "oklch(0.985 0 0)"
      }
    }
  ],
  "failures": []
}
```