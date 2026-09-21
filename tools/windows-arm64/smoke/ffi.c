#include <stdint.h>

typedef int32_t (*callback_t)(int32_t);

int32_t invoke_callback(callback_t callback, int32_t value)
{
    return callback(value);
}
