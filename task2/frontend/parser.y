%code requires { #include "ast.h" }
%{
#include "ast.h"
int yylex(void);
void yyerror(const char *s);
%}
%define parse.error detailed
%locations
%union { char *text; Node *tree; }
%token <text> IDENT NUMBER
%token INT PRINT IF ELSE WHILE EQ NE LE GE INVALID
%type <tree> program statements statement block expr
%left EQ NE
%left '<' '>' LE GE
%left '+' '-'
%left '*' '/' '%'
%precedence UMINUS
%%
program: statements { root = $1; $$ = $1; };
statements:
    %empty { $$ = node("block", "", 1, 1); }
  | statements statement { $$ = append($1, $2); }
;
block: '{' statements '}' { $$ = $2; $$->line=@1.first_line; $$->column=@1.first_column; };
statement:
    INT IDENT ';' { $$ = node("decl",$2,@1.first_line,@1.first_column); }
  | INT IDENT '=' expr ';' { $$ = make1("decl",$2,@1.first_line,@1.first_column,$4); }
  | IDENT '=' expr ';' { $$ = make1("assign",$1,@1.first_line,@1.first_column,$3); }
  | PRINT '(' expr ')' ';' { $$ = make1("print","",@1.first_line,@1.first_column,$3); }
  | IF '(' expr ')' block { $$ = make2("if","",@1.first_line,@1.first_column,$3,$5); }
  | IF '(' expr ')' block ELSE block { $$ = append(make2("if","",@1.first_line,@1.first_column,$3,$5),$7); }
  | WHILE '(' expr ')' block { $$ = make2("while","",@1.first_line,@1.first_column,$3,$5); }
  | block { $$ = $1; }
;
expr:
    NUMBER { $$ = node("number",$1,@1.first_line,@1.first_column); }
  | IDENT { $$ = node("name",$1,@1.first_line,@1.first_column); }
  | '(' expr ')' { $$ = $2; }
  | '-' expr %prec UMINUS { $$ = make1("unary","-",@1.first_line,@1.first_column,$2); }
  | expr '+' expr { $$ = make2("binary","+",@2.first_line,@2.first_column,$1,$3); }
  | expr '-' expr { $$ = make2("binary","-",@2.first_line,@2.first_column,$1,$3); }
  | expr '*' expr { $$ = make2("binary","*",@2.first_line,@2.first_column,$1,$3); }
  | expr '/' expr { $$ = make2("binary","/",@2.first_line,@2.first_column,$1,$3); }
  | expr '%' expr { $$ = make2("binary","%",@2.first_line,@2.first_column,$1,$3); }
  | expr '<' expr { $$ = make2("binary","<",@2.first_line,@2.first_column,$1,$3); }
  | expr '>' expr { $$ = make2("binary",">",@2.first_line,@2.first_column,$1,$3); }
  | expr LE expr { $$ = make2("binary","<=",@2.first_line,@2.first_column,$1,$3); }
  | expr GE expr { $$ = make2("binary",">=",@2.first_line,@2.first_column,$1,$3); }
  | expr EQ expr { $$ = make2("binary","==",@2.first_line,@2.first_column,$1,$3); }
  | expr NE expr { $$ = make2("binary","!=",@2.first_line,@2.first_column,$1,$3); }
;
%%
void yyerror(const char *s) { diagnostic("syntax",s,yylloc.first_line,yylloc.first_column); }
