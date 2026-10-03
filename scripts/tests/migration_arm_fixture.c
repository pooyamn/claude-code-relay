#include <stdint.h>

/* Compiler/linker acceptance only, not a board, flashing or USB test. */
volatile uint32_t migration_probe = UINT32_C(0x50434231);

int main(void) {
    return (int)migration_probe;
}
