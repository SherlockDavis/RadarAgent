module.exports = {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "type-enum": [
      2,
      "always",
      ["feat", "fix", "docs", "refactor", "test", "chore", "perf", "ci"],
    ],
    "scope-enum": [
      1,
      "always",
      [
        "plugin",
        "scheduler",
        "processor",
        "rag",
        "output",
        "config",
        "provider",
        "service",
        "web",
        "deps",
        "ci",
        "release",
      ],
    ],
    "subject-case": [0],
    "header-max-length": [2, "always", 100],
  },
};
