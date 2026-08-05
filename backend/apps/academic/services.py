"""Operações do app academic que cruzam mais de um model.

Vazio por enquanto. Só ganha função quando a criação de Teacher/Student
precisar escrever em Person, User e AuditLog na mesma transação — não
crie service "por simetria" (ADR-002).

Quando escrever aqui: chame `full_clean()` antes de `save()`. O Django não
executa `clean()` em `.save()`/`.create()`, só em formulário — sem essa
chamada o invariante de programa de Teacher, Student, CollectiveProject e
AcademicTerm nunca roda no caminho real.
"""
