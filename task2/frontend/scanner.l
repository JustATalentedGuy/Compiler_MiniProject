%option noyywrap nounput noinput never-interactive
%x COMMENT
%{
#include "parser.tab.h"
#include "ast.h"
static int current_line=1, current_column=1, comment_line, comment_column;
static void locate(const char *s, int length) {
    yylloc.first_line=current_line; yylloc.first_column=current_column;
    for (int i=0;i<length;i++) {
        yylloc.last_line=current_line; yylloc.last_column=current_column;
        if (s[i]=='\n') { current_line++; current_column=1; }
        else current_column++;
    }
}
#define YY_USER_ACTION locate(yytext,yyleng);
#define TOKEN(kind,name) log_token(name,yytext,yylloc.first_line,yylloc.first_column); return kind;
%}
%%
[ \t\r\n]+                 ;
"//"[^\n]*                  ;
"/*"                        { comment_line=yylloc.first_line; comment_column=yylloc.first_column; BEGIN(COMMENT); }
<COMMENT>"*/"               { BEGIN(INITIAL); }
<COMMENT>[^*\n]+            ;
<COMMENT>"*"                ;
<COMMENT>\n                 ;
<COMMENT><<EOF>>            { diagnostic("lexical","Unterminated block comment",comment_line,comment_column); BEGIN(INITIAL); return 0; }
"int"                       { TOKEN(INT,"INT") }
"print"                     { TOKEN(PRINT,"PRINT") }
"if"                        { TOKEN(IF,"IF") }
"else"                      { TOKEN(ELSE,"ELSE") }
"while"                     { TOKEN(WHILE,"WHILE") }
"=="                        { TOKEN(EQ,"EQ") }
"!="                        { TOKEN(NE,"NE") }
"<="                        { TOKEN(LE,"LE") }
">="                        { TOKEN(GE,"GE") }
[0-9]+                      { yylval.text=copy_text(yytext); TOKEN(NUMBER,"NUMBER") }
[A-Za-z_][A-Za-z_0-9]*      { yylval.text=copy_text(yytext); TOKEN(IDENT,"IDENT") }
[+*/%(){};=<>-]             { log_token("SYMBOL",yytext,yylloc.first_line,yylloc.first_column); return yytext[0]; }
.                           { log_token("INVALID",yytext,yylloc.first_line,yylloc.first_column); diagnostic("lexical","Invalid character",yylloc.first_line,yylloc.first_column); return INVALID; }
<<EOF>>                     { yylloc.first_line=current_line; yylloc.first_column=current_column; return 0; }
%%
