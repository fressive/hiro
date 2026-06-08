---
name: web-information-collecting
description: Collecting the information from a URL of a website. Use when exploiting a new host with HTTP service available.
---

## Input Format

A URL of the website to collect and a session ID should be provided.

## Instruction

### Before Each Step

1. Check the `INFO.md` to see whether similar step is executed. Only re-execute when you think it is necessary to find extra information.

### After Each Step

1. Use the log tool to inform the server what are you doing
2. Append some valuable information briefly in file `INFO.md` in the working directory, including what commands/skill/tool you have executed and the results. For example, if you executed dirsearch, then record like "dirsearch -u http://... executed, results saved to {workdir}/dirsearch.csv" in the `INFO.md`. MAKE SURE YOU ARE AWARE OF THIS PRINCIPLE.
3. Clean up some information in the context that may be deviated from the orientation.

### Steps

1. Determine the server address and recognized information (from `INFO.md` and provided hint) and try to spectulate valuable attack paths from recognized information.
2. Visit the given URL to retrieve some information.
3. If the information is not enough to point out a penetration orientation, use feroxbuster tool to scan the website to get more endpoints.
    - If backend source leakage is detected, use code-audit skill to audit the code finding possible exploits firstly.
4. Fetch the valuable paths with curl tool and try to determine the backend server based on the Server response header, if:
    - error response code(i.e. 400, 404, 500) are returned, the content is empty, or the website seems to be static without any possible exploit methods (try to find the vulnerability in web application first, not middleware).
    - any normal service is running on the path, try to use fingerprinting tool to recognize what service the website is (i.e. OA, CMS, BBS, CI, MinIO) and the service version. 
5. 
    - If the service is recognized, try to search related vulnerability vector in the database and try to exploit the website. 
    - If the service cannot be recognized, try to audit the html file.
6. Stop when you think the information collected is enough to solve the challenge or there is no more information you can collect at this stage.

## DO NOTs

1. DO NOT use bruteforce technology at anytime unless you have sufficient evidence. 