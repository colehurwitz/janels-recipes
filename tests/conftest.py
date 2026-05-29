def pytest_addoption(parser):
    # The factory's test-detector invokes the Node test path as
    #   npm test -- --passWithNoTests
    # (a Jest-style flag). With our script that becomes
    #   python3 -m pytest tests/ -q --passWithNoTests
    # Register --passWithNoTests as a known no-op so pytest does not abort on
    # the unknown argument when run via `npm test`.
    parser.addoption(
        '--passWithNoTests', action='store_true', default=False,
        help='No-op compatibility flag (ignored); accepted so pytest runs cleanly under npm test.'
    )
