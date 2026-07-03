// mt-compile: a MultiText-DSL COMPILE CHECK (no warren, no ranking).
//
// Reads a MultiText program from stdin -- `name = expr` macro definitions and
// `@rank TOPIC q0 q1 ...` tier lines, exactly as apps/mt.cc drives them -- and, for
// each statement, compiles it through cottontail::Mt::infix_expression(). Prints one
// line per statement: OK + the compiled Cottontail GCL s-expression, or ERROR + the
// parser's message. This is the validity oracle for the "can the LLM write valid
// MultiText?" scouting: exit code 0 iff every statement compiled.
//
// Output lines (tab-separated after the tag):
//   DEF  OK    <lhs=rhs>            \t <s-expression>
//   DEF  ERR   <line>              \t <error>
//   TIER OK    <topic> <name>      \t <s-expression>
//   TIER ERR   <topic> <name>      \t <error>
//   SUMMARY statements=<n> errors=<n>

#include <iostream>
#include <regex>
#include <string>
#include <vector>

#include "src/mt.h"

int main() {
  cottontail::Mt mt;
  std::string line;
  int statements = 0, errors = 0;
  while (std::getline(std::cin, line)) {
    // trim leading/trailing whitespace
    size_t a = line.find_first_not_of(" \t\r\n");
    if (a == std::string::npos)
      continue;
    size_t b = line.find_last_not_of(" \t\r\n");
    line = line.substr(a, b - a + 1);
    if (line.empty() || line[0] == '#' || line.rfind(";;", 0) == 0)
      continue; // blank / comment
    std::string error;
    if (line[0] == '@') {
      std::regex ws("\\s+");
      std::vector<std::string> cmd{
          std::sregex_token_iterator(line.begin(), line.end(), ws, -1), {}};
      if (cmd.size() > 1 && cmd[0] == "@rank") {
        // Tiers = every token after @rank. Tolerate a legacy leading NUMERIC topic
        // label (@rank 208 t0 t1 ...) by skipping it; the intent-driven form is
        // @rank t0 t1 ... with no topic.
        size_t first = 1;
        if (cmd.size() > 2 &&
            cmd[1].find_first_not_of("0123456789") == std::string::npos)
          first = 2;
        for (size_t i = first; i < cmd.size(); i++) {
          statements++;
          if (mt.infix_expression(cmd[i], &error))
            std::cout << "TIER\tOK\t" << cmd[i] << "\t" << mt.s_expression() << "\n";
          else {
            std::cout << "TIER\tERR\t" << cmd[i] << "\t" << error << "\n";
            errors++;
          }
        }
      } else {
        statements++;
        errors++;
        std::cout << "TIER\tERR\t" << line << "\tmalformed @rank line\n";
      }
    } else {
      statements++;
      if (mt.infix_expression(line, &error))
        std::cout << "DEF\tOK\t" << line << "\t" << mt.s_expression() << "\n";
      else {
        std::cout << "DEF\tERR\t" << line << "\t" << error << "\n";
        errors++;
      }
    }
  }
  std::cout << "SUMMARY statements=" << statements << " errors=" << errors << "\n";
  return errors == 0 ? 0 : 1;
}
