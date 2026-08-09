# fixture_repo

A deliberately tiny project the tests ask questions about.

It exists so that tool output is stable. Cassettes record the whole
conversation, and tool results are part of that conversation — if the tests
pointed at the real repository, editing any source file would invalidate every
cassette. Three small files that nothing else depends on will not move.
