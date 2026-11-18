/**
 * Starts the backend and resolves to the local auth token for the window.
 * @param {string} options_json
 * @returns {Promise<string>}
 */
function start(options_json) {
    const ptr0 = passStringToWasm0(options_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
    const len0 = WASM_VECTOR_LEN;
    const ret = wasm.start(ptr0, len0);
    return ret;
}
exports.start = start;
function __wbg_get_imports() {
    const import0 = {
        __proto__: null,
        __wbg_Error_208446807d0d1e30: function(arg0, arg1) {
            const ret = Error(getStringFromWasm0(arg0, arg1));
            return ret;
        },
        __wbg___wbindgen_is_function_741ff2bb612836f5: function(arg0) {
            const ret = typeof(arg0) === 'function';
            return ret;
        },
        __wbg___wbindgen_is_null_c22311b1cc228e3a: function(arg0) {
            const ret = arg0 === null;
            return ret;
        },
        __wbg___wbindgen_is_undefined_be5b34249ff1fc15: function(arg0) {
            const ret = arg0 === undefined;
            return ret;
        },
        __wbg___wbindgen_number_get_934b640d0889af78: function(arg0, arg1) {
            const obj = arg1;
            const ret = typeof(obj) === 'number' ? obj : undefined;
            getDataViewMemory0().setFloat64((arg0 >>> 0) + 8 * 1, isLikeNone(ret) ? 0 : ret, true);
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 0, !isLikeNone(ret), true);
        },
        __wbg___wbindgen_string_get_7ce8eee7fd327545: function(arg0, arg1) {
            const obj = arg1;
            const ret = typeof(obj) === 'string' ? obj : undefined;
            var ptr1 = isLikeNone(ret) ? 0 : passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            var len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 1, len1, true);
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 0, ptr1, true);
        },
        __wbg___wbindgen_throw_4c88d8bf264fd984: function(arg0, arg1) {
            throw new Error(getStringFromWasm0(arg0, arg1));
        },
        __wbg__wbg_cb_unref_09736879a3f67559: function(arg0) {
            arg0._wbg_cb_unref();
        },
        __wbg_accept_92810a7835bb9430: function(arg0) {
            const ret = jarvisHost.accept(arg0 >>> 0);
            return ret;
        },
        __wbg_appendFile_cd26d6d0cdab8fb3: function() { return handleError(function (arg0, arg1, arg2, arg3) {
            jarvisHost.appendFile(getStringFromWasm0(arg0, arg1), getArrayU8FromWasm0(arg2, arg3));
        }, arguments); },
        __wbg_bodyClose_4bf149dc3d33c36b: function(arg0) {
            jarvisHost.bodyClose(arg0 >>> 0);
        },
        __wbg_bodyRead_090a82bbef3c8716: function(arg0) {
            const ret = jarvisHost.bodyRead(arg0 >>> 0);
            return ret;
        },
        __wbg_call_a410eb4b59ed5965: function() { return handleError(function (arg0, arg1, arg2) {
            const ret = arg0.call(arg1, arg2);
            return ret;
        }, arguments); },
        __wbg_close_8817878f7e524a8b: function(arg0) {
            jarvisHost.close(arg0 >>> 0);
        },
        __wbg_createFile_d341d6e662bc8176: function(arg0, arg1, arg2, arg3, arg4) {
            const ret = jarvisHost.createFile(getStringFromWasm0(arg1, arg2), getArrayU8FromWasm0(arg3, arg4));
            const ptr1 = passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            const len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 1, len1, true);
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 0, ptr1, true);
        },
        __wbg_envJson_495efdcd4d044cb8: function(arg0) {
            const ret = jarvisHost.envJson();
            const ptr1 = passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            const len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 1, len1, true);
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 0, ptr1, true);
        },
        __wbg_exit_1b33c5f64d6d68d0: function(arg0) {
            jarvisHost.exit(arg0);
        },
        __wbg_fetchStart_dd7d8c218c25a761: function(arg0, arg1, arg2, arg3, arg4, arg5, arg6, arg7, arg8) {
            const ret = jarvisHost.fetchStart(getStringFromWasm0(arg0, arg1), getStringFromWasm0(arg2, arg3), getStringFromWasm0(arg4, arg5), getArrayU8FromWasm0(arg6, arg7), arg8);
            return ret;
        },
        __wbg_formatToParts_cf3a0b0f7fb5cc97: function(arg0, arg1) {
            const ret = arg0.formatToParts(arg1);
            return ret;
        },
        __wbg_getDate_a44b5f4a8c42a3c3: function(arg0) {
            const ret = arg0.getDate();
            return ret;
        },
        __wbg_getDay_0ea3aef4bf721d1c: function(arg0) {
            const ret = arg0.getDay();
            return ret;
        },
        __wbg_getFullYear_94114da14f235fca: function(arg0) {
            const ret = arg0.getFullYear();
            return ret;
        },
        __wbg_getHours_d55d13f9f95415bb: function(arg0) {
            const ret = arg0.getHours();
            return ret;
        },
        __wbg_getMilliseconds_ea096e97ccdd1beb: function(arg0) {
            const ret = arg0.getMilliseconds();
            return ret;
        },
        __wbg_getMinutes_d0d71c490ef83b47: function(arg0) {
            const ret = arg0.getMinutes();
            return ret;
        },
        __wbg_getMonth_a4698d688e95d9bd: function(arg0) {
            const ret = arg0.getMonth();
            return ret;
        },
        __wbg_getSeconds_7143dabeecfaf7d1: function(arg0) {
            const ret = arg0.getSeconds();
            return ret;
        },
        __wbg_getTime_edc91481cbc4cd78: function(arg0) {
            const ret = arg0.getTime();
            return ret;
        },
        __wbg_getTimezoneOffset_87127d92c2c117e9: function(arg0) {
            const ret = arg0.getTimezoneOffset();
            return ret;
        },
        __wbg_get_2080c49015e35254: function() { return handleError(function (arg0, arg1) {
            const ret = Reflect.get(arg0, arg1);
            return ret;
        }, arguments); },
        __wbg_get_unchecked_e6325ad374eff861: function(arg0, arg1) {
            const ret = arg0[arg1 >>> 0];
            return ret;
        },
        __wbg_hostname_d41369bbb1e2cd21: function(arg0, arg1) {
            const ret = arg1.hostname;
            const ptr1 = passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            const len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 1, len1, true);
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 0, ptr1, true);
        },
        __wbg_href_85e2360e3eb62186: function(arg0, arg1) {
            const ret = arg1.href;
            const ptr1 = passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            const len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 1, len1, true);
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 0, ptr1, true);
        },
        __wbg_instanceof_Error_74e3cca0c4a69161: function(arg0) {
            let result;
            try {
                result = arg0 instanceof Error;
            } catch (_) {
                result = false;
            }
            const ret = result;
            return ret;
        },
        __wbg_length_186163212ffe79c3: function(arg0) {
            const ret = arg0.length;
            return ret;
        },
        __wbg_length_b03a0fabb109b1e9: function(arg0) {
            const ret = arg0.length;
            return ret;
        },
        __wbg_listDir_c27f262595477b20: function(arg0, arg1, arg2) {
            const ret = jarvisHost.listDir(getStringFromWasm0(arg1, arg2));
            var ptr1 = isLikeNone(ret) ? 0 : passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            var len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 1, len1, true);
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 0, ptr1, true);
        },
        __wbg_listen_1225799a7218b687: function(arg0, arg1, arg2) {
            const ret = jarvisHost.listen(getStringFromWasm0(arg0, arg1), arg2);
            return ret;
        },
        __wbg_log_0316bda9771b5916: function(arg0, arg1, arg2, arg3) {
            jarvisHost.log(getStringFromWasm0(arg0, arg1), getStringFromWasm0(arg2, arg3));
        },
        __wbg_message_43d8c8f1d543a349: function(arg0) {
            const ret = arg0.message;
            return ret;
        },
        __wbg_mkdirp_5506c1d224acb493: function() { return handleError(function (arg0, arg1) {
            jarvisHost.mkdirp(getStringFromWasm0(arg0, arg1));
        }, arguments); },
        __wbg_monotonic_dddb108bef973d92: function() {
            const ret = jarvisHost.monotonic();
            return ret;
        },
        __wbg_new_0_36d738a0c8cfac43: function() {
            const ret = new Date();
            return ret;
        },
        __wbg_new_13de428334042d26: function(arg0) {
            const ret = new Uint8Array(arg0);
            return ret;
        },
        __wbg_new_3e95cd7386bb9a6c: function(arg0) {
            const ret = new Date(arg0);
            return ret;
        },
        __wbg_new_4c069f6c1114791c: function(arg0, arg1) {
            const ret = new Intl.DateTimeFormat(arg0, arg1);
            return ret;
        },
        __wbg_new_cd4348290afae586: function() {
            const ret = new Object();
            return ret;
        },
        __wbg_new_ebddf97c6a636098: function() { return handleError(function (arg0, arg1) {
            const ret = new URL(getStringFromWasm0(arg0, arg1));
            return ret;
        }, arguments); },
        __wbg_new_typed_e09da9dae6ee5935: function(arg0, arg1) {
            try {
                var state0 = {a: arg0, b: arg1};
                var cb0 = (arg0, arg1) => {
                    const a = state0.a;
                    state0.a = 0;
                    try {
                        return wasm_bindgen_283ca66947321775___convert__closures_____invoke___js_sys_8c64336f9522d733___Function_fn_wasm_bindgen_283ca66947321775___JsValue_____wasm_bindgen_283ca66947321775___sys__Undefined___js_sys_8c64336f9522d733___Function_fn_wasm_bindgen_283ca66947321775___JsValue_____wasm_bindgen_283ca66947321775___sys__Undefined_______true_(a, state0.b, arg0, arg1);
                    } finally {
                        state0.a = a;
                    }
                };
                const ret = new Promise(cb0);
                return ret;
            } finally {
                state0.a = 0;
            }
        },
        __wbg_normalize_2d352f86793b4b5f: function(arg0, arg1, arg2) {
            const ret = arg0.normalize(getStringFromWasm0(arg1, arg2));
            return ret;
        },
        __wbg_now_463ac581d2fc7ea3: function() {
            const ret = Date.now();
            return ret;
        },
        __wbg_of_027eb15371aac932: function(arg0) {
            const ret = Array.of(arg0);
            return ret;
        },
        __wbg_password_7e5fde5277a34107: function(arg0, arg1) {
            const ret = arg1.password;
            const ptr1 = passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            const len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 1, len1, true);
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 0, ptr1, true);
        },
        __wbg_pathsJson_51d53decc8c31806: function(arg0) {
            const ret = jarvisHost.pathsJson();
            const ptr1 = passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            const len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 1, len1, true);
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 0, ptr1, true);
        },
        __wbg_procKill_290bfc8718046d53: function(arg0) {
            jarvisHost.procKill(arg0 >>> 0);
        },
        __wbg_procRead_874539df94306351: function(arg0) {
            const ret = jarvisHost.procRead(arg0 >>> 0);
            return ret;
        },
        __wbg_procStart_9bbfca374731513b: function() { return handleError(function (arg0, arg1, arg2, arg3, arg4, arg5) {
            const ret = jarvisHost.procStart(getStringFromWasm0(arg0, arg1), getStringFromWasm0(arg2, arg3), getStringFromWasm0(arg4, arg5));
            return ret;
        }, arguments); },
        __wbg_procWait_44787282f0d95dab: function(arg0) {
            const ret = jarvisHost.procWait(arg0 >>> 0);
            return ret;
        },
        __wbg_protocol_1afd074503396d91: function(arg0, arg1) {
            const ret = arg1.protocol;
            const ptr1 = passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            const len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 1, len1, true);
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 0, ptr1, true);
        },
        __wbg_prototypesetcall_13162965d1fe7aa3: function(arg0, arg1, arg2) {
            Uint8Array.prototype.set.call(getArrayU8FromWasm0(arg0, arg1), arg2);
        },
        __wbg_psCall_84d2b247e759341e: function(arg0, arg1) {
            const ret = jarvisHost.psCall(getStringFromWasm0(arg0, arg1));
            return ret;
        },
        __wbg_psSetScript_e3b26a96969fdc2f: function(arg0, arg1) {
            jarvisHost.psSetScript(getStringFromWasm0(arg0, arg1));
        },
        __wbg_queueMicrotask_1e8503a8a690f0a3: function(arg0) {
            const ret = arg0.queueMicrotask;
            return ret;
        },
        __wbg_queueMicrotask_4a1a4d8dd332373b: function(arg0) {
            queueMicrotask(arg0);
        },
        __wbg_randomBytes_ecbc6e19f86ca1a8: function(arg0, arg1) {
            const ret = jarvisHost.randomBytes(arg1 >>> 0);
            const ptr1 = passArray8ToWasm0(ret, wasm.__wbindgen_malloc);
            const len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 1, len1, true);
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 0, ptr1, true);
        },
        __wbg_readFile_a0eb650a9b41424c: function(arg0, arg1, arg2) {
            const ret = jarvisHost.readFile(getStringFromWasm0(arg1, arg2));
            var ptr1 = isLikeNone(ret) ? 0 : passArray8ToWasm0(ret, wasm.__wbindgen_malloc);
            var len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 1, len1, true);
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 0, ptr1, true);
        },
        __wbg_read_a6f4fbf2d5e4e9c6: function(arg0) {
            const ret = jarvisHost.read(arg0 >>> 0);
            return ret;
        },
        __wbg_remove_8da47b153ef8017c: function(arg0, arg1) {
            const ret = jarvisHost.remove(getStringFromWasm0(arg0, arg1));
            return ret;
        },
        __wbg_rename_bbf99ebbb561bf39: function() { return handleError(function (arg0, arg1, arg2, arg3) {
            jarvisHost.rename(getStringFromWasm0(arg0, arg1), getStringFromWasm0(arg2, arg3));
        }, arguments); },
        __wbg_resolve_dbf78ab4942478b0: function(arg0) {
            const ret = Promise.resolve(arg0);
            return ret;
        },
        __wbg_restart_5e3a29362463c96b: function() {
            jarvisHost.restart();
        },
        __wbg_run_ca9362624847b5f3: function(arg0, arg1, arg2, arg3, arg4, arg5) {
            const ret = jarvisHost.run(getStringFromWasm0(arg0, arg1), getStringFromWasm0(arg2, arg3), getStringFromWasm0(arg4, arg5));
            return ret;
        },
        __wbg_setChildEnvBlocklist_0d84cfd8b06aadb6: function(arg0, arg1) {
            jarvisHost.setChildEnvBlocklist(getStringFromWasm0(arg0, arg1));
        },
        __wbg_setDate_0d5099503cd50b2d: function(arg0, arg1) {
            const ret = arg0.setDate(arg1 >>> 0);
            return ret;
        },
        __wbg_setHours_2eaebf1b39ef0c37: function(arg0, arg1) {
            const ret = arg0.setHours(arg1 >>> 0);
            return ret;
        },
        __wbg_setMilliseconds_6b9559b4d885b564: function(arg0, arg1) {
            const ret = arg0.setMilliseconds(arg1 >>> 0);
            return ret;
        },
        __wbg_setMinutes_e942d59d70c306d2: function(arg0, arg1) {
            const ret = arg0.setMinutes(arg1 >>> 0);
            return ret;
        },
        __wbg_setSeconds_59bd25028d372b86: function(arg0, arg1) {
            const ret = arg0.setSeconds(arg1 >>> 0);
            return ret;
        },
        __wbg_set_2793479888329cb6: function() { return handleError(function (arg0, arg1, arg2) {
            const ret = Reflect.set(arg0, arg1, arg2);
            return ret;
        }, arguments); },
        __wbg_sleep_e09be38a740924b4: function(arg0) {
            const ret = jarvisHost.sleep(arg0);
            return ret;
        },
        __wbg_spawnDetached_5c9606c139d8c6da: function(arg0, arg1, arg2, arg3, arg4, arg5) {
            const ret = jarvisHost.spawnDetached(getStringFromWasm0(arg0, arg1), getStringFromWasm0(arg2, arg3), getStringFromWasm0(arg4, arg5));
            return ret;
        },
        __wbg_sqlExec_c3d378677dca531a: function() { return handleError(function (arg0, arg1, arg2) {
            jarvisHost.sqlExec(arg0 >>> 0, getStringFromWasm0(arg1, arg2));
        }, arguments); },
        __wbg_sqlOpen_94407e2388c617e5: function() { return handleError(function (arg0, arg1) {
            const ret = jarvisHost.sqlOpen(getStringFromWasm0(arg0, arg1));
            return ret;
        }, arguments); },
        __wbg_sqlQuery_1c33fdfbd70c8170: function() { return handleError(function (arg0, arg1, arg2, arg3, arg4, arg5) {
            const ret = jarvisHost.sqlQuery(arg1 >>> 0, getStringFromWasm0(arg2, arg3), getStringFromWasm0(arg4, arg5));
            const ptr1 = passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            const len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 1, len1, true);
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 0, ptr1, true);
        }, arguments); },
        __wbg_sqlRun_a14c9b06569a609d: function() { return handleError(function (arg0, arg1, arg2, arg3, arg4, arg5) {
            const ret = jarvisHost.sqlRun(arg1 >>> 0, getStringFromWasm0(arg2, arg3), getStringFromWasm0(arg4, arg5));
            const ptr1 = passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            const len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 1, len1, true);
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 0, ptr1, true);
        }, arguments); },
        __wbg_stat_dea9acd8d5d5950b: function(arg0, arg1, arg2) {
            const ret = jarvisHost.stat(getStringFromWasm0(arg1, arg2));
            var ptr1 = isLikeNone(ret) ? 0 : passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            var len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 1, len1, true);
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 0, ptr1, true);
        },
        __wbg_static_accessor_GLOBAL_THIS_003ee833af9699fc: function() {
            const ret = typeof globalThis === 'undefined' ? undefined : globalThis;
            return isLikeNone(ret) ? 0 : addToExternrefTable0(ret);
        },
        __wbg_static_accessor_GLOBAL_e4293fb22cbe77da: function() {
            const ret = typeof global === 'undefined' ? undefined : global;
            return isLikeNone(ret) ? 0 : addToExternrefTable0(ret);
        },
        __wbg_static_accessor_SELF_53bb20457401453d: function() {
            const ret = typeof self === 'undefined' ? undefined : self;
            return isLikeNone(ret) ? 0 : addToExternrefTable0(ret);
        },
        __wbg_static_accessor_WINDOW_b5e0810bfecb7feb: function() {
            const ret = typeof window === 'undefined' ? undefined : window;
            return isLikeNone(ret) ? 0 : addToExternrefTable0(ret);
        },
        __wbg_then_656f253a5dd7d8ea: function(arg0, arg1, arg2) {
            const ret = arg0.then(arg1, arg2);
            return ret;
        },
        __wbg_then_e3f7f2d365708be8: function(arg0, arg1) {
            const ret = arg0.then(arg1);
            return ret;
        },
        __wbg_toISOString_51ebc75332aba76a: function(arg0) {
            const ret = arg0.toISOString();
            return ret;
        },
        __wbg_username_fce364447cfe79c4: function(arg0, arg1) {
            const ret = arg1.username;
            const ptr1 = passStringToWasm0(ret, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            const len1 = WASM_VECTOR_LEN;
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 1, len1, true);
            getDataViewMemory0().setInt32((arg0 >>> 0) + 4 * 0, ptr1, true);
        },
        __wbg_writeFile_63eccd0fb4de2cb8: function() { return handleError(function (arg0, arg1, arg2, arg3) {
            jarvisHost.writeFile(getStringFromWasm0(arg0, arg1), getArrayU8FromWasm0(arg2, arg3));
        }, arguments); },
        __wbg_write_7e1d0de117014416: function(arg0, arg1, arg2) {
            jarvisHost.write(arg0 >>> 0, getArrayU8FromWasm0(arg1, arg2));
        },
        __wbg_wsClose_7316982c0b2304c7: function(arg0) {
            jarvisHost.wsClose(arg0 >>> 0);
        },
        __wbg_wsConnect_00579b31424d5f2e: function(arg0, arg1, arg2, arg3, arg4, arg5, arg6) {
            const ret = jarvisHost.wsConnect(getStringFromWasm0(arg0, arg1), getStringFromWasm0(arg2, arg3), getStringFromWasm0(arg4, arg5), arg6);
            return ret;
        },
        __wbg_wsRecv_abb66ba3cca1f755: function(arg0) {
            const ret = jarvisHost.wsRecv(arg0 >>> 0);
            return ret;
        },
        __wbg_wsSendText_2d214bf774369e7e: function(arg0, arg1, arg2) {
            jarvisHost.wsSendText(arg0 >>> 0, getStringFromWasm0(arg1, arg2));
        },
        __wbindgen_generic_0000000000000001: function(arg0, arg1) {
            // Cast intrinsic for `Closure(Closure { owned: true, function: Function { arguments: [Externref], shim_idx: 677, ret: Result(Unit), inner_ret: Some(Result(Unit)) }, mutable: true }) -> Externref`.
            const ret = makeMutClosure(arg0, arg1, wasm_bindgen_283ca66947321775___convert__closures_____invoke___wasm_bindgen_283ca66947321775___JsValue__core_37ee0ce0c4cd57d5___result__Result_____wasm_bindgen_283ca66947321775___JsError___true_);
            return ret;
        },
        __wbindgen_generic_0000000000000002: function(arg0) {
            // Cast intrinsic for `F64 -> Externref`.
            const ret = arg0;
            return ret;
        },
        __wbindgen_generic_0000000000000003: function(arg0, arg1) {
            // Cast intrinsic for `Ref(String) -> Externref`.
            const ret = getStringFromWasm0(arg0, arg1);
            return ret;
        },
        __wbindgen_init_externref_table: function() {
            const table = wasm.__wbindgen_externrefs;
            table.set(0, undefined);
            table.set(1024, undefined);
            table.set(1025, null);
            table.set(1026, true);
            table.set(1027, false);
        },
    };
    return {
        __proto__: null,
        "./jarvis_bg.js": import0,
    };
}

function wasm_bindgen_283ca66947321775___convert__closures_____invoke___wasm_bindgen_283ca66947321775___JsValue__core_37ee0ce0c4cd57d5___result__Result_____wasm_bindgen_283ca66947321775___JsError___true_(arg0, arg1, arg2) {
    const ret = wasm.wasm_bindgen_283ca66947321775___convert__closures_____invoke___wasm_bindgen_283ca66947321775___JsValue__core_37ee0ce0c4cd57d5___result__Result_____wasm_bindgen_283ca66947321775___JsError___true_(arg0, arg1, arg2);
    if (ret[1]) {
        throw takeFromExternrefTable0(ret[0]);
    }
}

function wasm_bindgen_283ca66947321775___convert__closures_____invoke___js_sys_8c64336f9522d733___Function_fn_wasm_bindgen_283ca66947321775___JsValue_____wasm_bindgen_283ca66947321775___sys__Undefined___js_sys_8c64336f9522d733___Function_fn_wasm_bindgen_283ca66947321775___JsValue_____wasm_bindgen_283ca66947321775___sys__Undefined_______true_(arg0, arg1, arg2, arg3) {
    wasm.wasm_bindgen_283ca66947321775___convert__closures_____invoke___js_sys_8c64336f9522d733___Function_fn_wasm_bindgen_283ca66947321775___JsValue_____wasm_bindgen_283ca66947321775___sys__Undefined___js_sys_8c64336f9522d733___Function_fn_wasm_bindgen_283ca66947321775___JsValue_____wasm_bindgen_283ca66947321775___sys__Undefined_______true_(arg0, arg1, arg2, arg3);
}

function addToExternrefTable0(obj) {
    const idx = wasm.__externref_table_alloc();
    wasm.__wbindgen_externrefs.set(idx, obj);
    return idx;
}

const CLOSURE_DTORS = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(state => wasm.__wbindgen_destroy_closure(state.a, state.b));

function getArrayU8FromWasm0(ptr, len) {
    ptr = ptr >>> 0;
    return getUint8ArrayMemory0().subarray(ptr / 1, ptr / 1 + len);
}

let cachedDataViewMemory0 = null;
function getDataViewMemory0() {
    if (cachedDataViewMemory0 === null || cachedDataViewMemory0.buffer.detached === true || (cachedDataViewMemory0.buffer.detached === undefined && cachedDataViewMemory0.buffer !== wasm.memory.buffer)) {
        cachedDataViewMemory0 = new DataView(wasm.memory.buffer);
    }
    return cachedDataViewMemory0;
}

function getStringFromWasm0(ptr, len) {
    ptr = ptr >>> 0;
    return decodeText(getUint8ArrayMemory0().subarray(ptr, ptr + len));
}

let cachedUint8ArrayMemory0 = null;
function getUint8ArrayMemory0() {
    if (cachedUint8ArrayMemory0 === null || cachedUint8ArrayMemory0.byteLength === 0) {
        cachedUint8ArrayMemory0 = new Uint8Array(wasm.memory.buffer);
    }
    return cachedUint8ArrayMemory0;
}

function handleError(f, args) {
    try {
        return f.apply(this, args);
    } catch (e) {
        const idx = addToExternrefTable0(e);
        wasm.__wbindgen_exn_store(idx);
    }
}

function isLikeNone(x) {
    return x === undefined || x === null;
}

function makeMutClosure(arg0, arg1, f) {
    const state = { a: arg0, b: arg1, cnt: 1 };
    const real = (...args) => {

        // First up with a closure we increment the internal reference
        // count. This ensures that the Rust closure environment won't
        // be deallocated while we're invoking it.
        state.cnt++;
        const a = state.a;
        state.a = 0;
        try {
            return f(a, state.b, ...args);
        } finally {
            state.a = a;
            real._wbg_cb_unref();
        }
    };
    real._wbg_cb_unref = () => {
        if (--state.cnt === 0) {
            wasm.__wbindgen_destroy_closure(state.a, state.b);
            state.a = 0;
            CLOSURE_DTORS.unregister(state);
        }
    };
    CLOSURE_DTORS.register(real, state, state);
    return real;
}

function passArray8ToWasm0(arg, malloc) {
    const ptr = malloc(arg.length * 1, 1) >>> 0;
    getUint8ArrayMemory0().set(arg, ptr / 1);
    WASM_VECTOR_LEN = arg.length;
    return ptr;
}

function passStringToWasm0(arg, malloc, realloc) {
    if (realloc === undefined) {
        const buf = cachedTextEncoder.encode(arg);
        const ptr = malloc(buf.length, 1) >>> 0;
        getUint8ArrayMemory0().subarray(ptr, ptr + buf.length).set(buf);
        WASM_VECTOR_LEN = buf.length;
        return ptr;
    }

    let len = arg.length;
    let ptr = malloc(len, 1) >>> 0;

    const mem = getUint8ArrayMemory0();

    let offset = 0;

    for (; offset < len; offset++) {
        const code = arg.charCodeAt(offset);
        if (code > 0x7F) break;
        mem[ptr + offset] = code;
    }
    if (offset !== len) {
        if (offset !== 0) {
            arg = arg.slice(offset);
        }
        ptr = realloc(ptr, len, len = offset + arg.length * 3, 1) >>> 0;
        const view = getUint8ArrayMemory0().subarray(ptr + offset, ptr + len);
        const ret = cachedTextEncoder.encodeInto(arg, view);

        offset += ret.written;
        ptr = realloc(ptr, len, offset, 1) >>> 0;
    }

    WASM_VECTOR_LEN = offset;
    return ptr;
}

function takeFromExternrefTable0(idx) {
    const value = wasm.__wbindgen_externrefs.get(idx);
    wasm.__externref_table_dealloc(idx);
    return value;
}

let cachedTextDecoder = new TextDecoder('utf-8', { ignoreBOM: true });
cachedTextDecoder.decode();
function decodeText(bytes) {
    return cachedTextDecoder.decode(bytes);
}

const cachedTextEncoder = new TextEncoder();

if (!('encodeInto' in cachedTextEncoder)) {
    cachedTextEncoder.encodeInto = function (arg, view) {
        const buf = cachedTextEncoder.encode(arg);
        view.set(buf);
        return {
            read: arg.length,
            written: buf.length
        };
    };
}

let WASM_VECTOR_LEN = 0;

const wasmPath = `${__dirname}/jarvis_bg.wasm`;
const wasmBytes = require('fs').readFileSync(wasmPath);
const wasmModule = new WebAssembly.Module(wasmBytes);
let wasmInstance = new WebAssembly.Instance(wasmModule, __wbg_get_imports());
let wasm = wasmInstance.exports;
wasm.__wbindgen_start();
