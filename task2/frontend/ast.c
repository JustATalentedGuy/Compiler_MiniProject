#include "ast.h"
#include <stdlib.h>
#include <string.h>
#include "parser.tab.h"

Node *root;
int error_count;
static FILE *tokens, *errors;
static int token_count, diagnostic_count;
extern FILE *yyin;
extern int yylex(void);

static void *checked(void *p) { if (!p) { fputs("Out of memory\n", stderr); exit(2); } return p; }
char *copy_text(const char *s) {
    char *p = checked(malloc(strlen(s) + 1)); strcpy(p, s); return p;
}
Node *node(const char *kind, const char *value, int line, int column) {
    Node *n = checked(calloc(1, sizeof(Node)));
    n->kind = copy_text(kind); n->value = copy_text(value);
    n->line = line; n->column = column; return n;
}
Node *append(Node *p, Node *c) {
    p->children = checked(realloc(p->children, (p->count + 1) * sizeof(Node *)));
    p->children[p->count++] = c; return p;
}
Node *make1(const char *k, const char *v, int l, int c, Node *a) { return append(node(k,v,l,c),a); }
Node *make2(const char *k, const char *v, int l, int c, Node *a, Node *b) { return append(make1(k,v,l,c,a),b); }
static void quoted(FILE *f, const char *s) {
    fputc('"', f);
    for (; *s; s++) {
        unsigned char ch = (unsigned char)*s;
        switch (ch) {
            case '"': fputs("\\\"", f); break;
            case '\\': fputs("\\\\", f); break;
            case '\n': fputs("\\n", f); break;
            case '\r': fputs("\\r", f); break;
            case '\t': fputs("\\t", f); break;
            default: if (ch < 32 || ch >= 127) fprintf(f,"\\u%04x",ch); else fputc(ch,f);
        }
    }
    fputc('"', f);
}
void log_token(const char *type, const char *text, int line, int column) {
    if (token_count++) fputc(',',tokens);
    fputs("{\"type\":",tokens); quoted(tokens,type);
    fputs(",\"lexeme\":",tokens); quoted(tokens,text);
    fprintf(tokens,",\"line\":%d,\"column\":%d}",line,column);
}
void diagnostic(const char *phase, const char *message, int line, int column) {
    error_count++;
    if (diagnostic_count++) fputc(',',errors);
    fputs("{\"phase\":",errors); quoted(errors,phase);
    fputs(",\"message\":",errors); quoted(errors,message);
    fprintf(errors,",\"line\":%d,\"column\":%d}",line,column);
}
static void dump_node(Node *n) {
    if (!n) { fputs("null",stdout); return; }
    fputs("{\"kind\":",stdout); quoted(stdout,n->kind);
    fputs(",\"value\":",stdout); quoted(stdout,n->value);
    printf(",\"line\":%d,\"column\":%d,\"children\":[",n->line,n->column);
    for (int i=0;i<n->count;i++) { if (i) putchar(','); dump_node(n->children[i]); }
    fputs("]}",stdout);
}
static void copy_stream(FILE *f) { int c; rewind(f); while ((c=fgetc(f))!=EOF) putchar(c); }
int main(void) {
    tokens=tmpfile(); errors=tmpfile(); checked(tokens); checked(errors);
    yyin=stdin;
    yyparse();
    /* Finish scanning even after an unrecoverable parse error to show every token. */
    while (yylex()) {}
    fputs("{\"tokens\":[",stdout); copy_stream(tokens);
    fputs("],\"diagnostics\":[",stdout); copy_stream(errors);
    fputs("],\"ast\":",stdout); dump_node(error_count ? NULL : root);
    puts("}"); fclose(tokens); fclose(errors);
    return error_count ? 1 : 0;
}
