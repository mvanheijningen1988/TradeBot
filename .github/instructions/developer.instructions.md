---
name: "Developer Instructions"
description: ""
---

# Developer Instructions
This file contains instructions on how to contribute to the project, including code style guidelines, testing procedures, and other best practices for developers. Please read through these instructions carefully before making any contributions to ensure consistency and maintainability of the codebase.

1. Development
Make changes in a new branch based on the `main` branch. Follow the code style guidelines outlined in the project documentation, and ensure that your code is well-documented. Use meaningful commit messages that describe the changes you have made. When your changes are ready, create a pull request and request a review from the maintainers.

Update the version number. Manager, UI and Workers should have isolated version numbers that are updated independently based on changes to each component. Update the CHANGELOG.md file with a summary of your changes, following the format used in previous entries. Include any relevant details about the changes, such as new features, bug fixes, or breaking changes. This will help maintain a clear history of the project's development and make it easier for users to understand what has changed in each release.

2. Testing
Run unit tests for the components you have modified. Ensure that all tests pass before submitting your pull request. If you have added new features, add new tests to cover those features.

3. Publishing
Run docker compose build to build the updated images for the manager, UI, and workers. Push the updated images to the local docker registry. Update any deployment scripts or configurations to use the new image versions.

4. Documentation

Update the CHANGELOG.md file with a summary of your changes, following the format used in previous entries. Include any relevant details about the changes, such as new features, bug fixes, or breaking changes. This will help maintain a clear history of the project's development and make it easier for users to understand what has changed in each release.