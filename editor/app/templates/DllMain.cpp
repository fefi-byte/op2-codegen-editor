#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <HFL/Source/HFL.h>

BOOL APIENTRY DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved)
{
	if (fdwReason == DLL_PROCESS_ATTACH)
	{
		DisableThreadLibraryCalls(hinstDLL);
		HFLInit();
	}
	else if (fdwReason == DLL_PROCESS_DETACH)
	{
		HFLCleanup();
	}

	return true;
}
