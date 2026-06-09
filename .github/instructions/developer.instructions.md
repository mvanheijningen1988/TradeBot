---
name: "Developer Instructions"
description: ""
---

# Developer Instructions
This file contains instructions on how to contribute to the project, including code style guidelines, testing procedures, and other best practices for developers. Please read through these instructions carefully before making any contributions to ensure consistency and maintainability of the codebase.

1. Development
Use a development-based flow:
- Create feature branches from `development`.
- Open pull requests from feature branches into `development`.
- Merge validated feature work into `development` first.
- Merge `development` into `main` using a **squash commit**.

Follow the code style guidelines outlined in the project documentation, and ensure that your code is well-documented. Use meaningful commit messages that describe the changes you have made. When your changes are ready, create a pull request and request a review from the maintainers.

Commit messages must accurately reflect the actual changes in the commit. Avoid vague messages; include the functional area and the concrete change.

Update the version number. Manager, UI and Workers should have isolated version numbers that are updated independently based on changes to each component. Update the CHANGELOG.md file with a summary of your changes, following the format used in previous entries. Include any relevant details about the changes, such as new features, bug fixes, or breaking changes. This will help maintain a clear history of the project's development and make it easier for users to understand what has changed in each release.

2. Testing
Run unit tests for the components you have modified. Ensure that all tests pass before submitting your pull request. If you have added new features, add new tests to cover those features.

3. Publishing
Publishing is split by branch target:
- `development` branch publishes changed component images with `-dev` semantic version tags for swarm/dev validation.
- `main` branch publishes changed component images with standard semantic version tags.

For local validation, run docker compose build to build the updated images for the manager, UI, and workers. Push the updated images to the local docker registry if required by your setup. Update any deployment scripts or configurations to use the new image versions.

4. Documentation

Update the CHANGELOG.md file with a summary of your changes, following the format used in previous entries. Include any relevant details about the changes, such as new features, bug fixes, or breaking changes. This will help maintain a clear history of the project's development and make it easier for users to understand what has changed in each release.

When changes affect behavior, configuration, setup, APIs, or workflows, also update README.md accordingly. Before opening a pull request, verify that both CHANGELOG.md and README.md were reviewed and updated where applicable.
