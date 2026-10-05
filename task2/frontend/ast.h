#ifndef MINI_AST_H
#define MINI_AST_H
#include <stdio.h>
typedef struct Node {
    char *kind, *value;
    int line, column, count;
    struct Node **children;
} Node;
char *copy_text(const char *s);
Node *node(const char *kind, const char *value, int line, int column);
Node *append(Node *parent, Node *child);
Node *make1(const char *kind, const char *value, int line, int column, Node *a);
Node *make2(const char *kind, const char *value, int line, int column, Node *a, Node *b);
void log_token(const char *type, const char *text, int line, int column);
void diagnostic(const char *phase, const char *message, int line, int column);
extern Node *root;
extern int error_count;
#endif
