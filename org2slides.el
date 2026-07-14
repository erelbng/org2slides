;;; org2slides.el --- Export reveal.js org decks to HTML + Beamer PDF -*- lexical-binding: t; -*-

;; Emacs front-end for the `org2slides' script: one command exports the
;; current reveal.js org deck to <deck>.html (reveal presentation) and
;; <deck>_beamer.pdf. Runs asynchronously in a *org2slides* compilation
;; buffer; the PDF opens automatically on success.
;;
;;   M-x org2slides-export        both HTML + PDF   (C-u: --debug)
;;   M-x org2slides-export-pdf    PDF only          (C-u: --debug)
;;   M-x org2slides-export-html   HTML only
;;
;; Also in the `C-c C-e' export dispatcher under `s':
;;   s s  HTML + PDF          s h  HTML only
;;   s p  PDF only            s d  PDF, keep intermediates (--debug)
;;   s l  PDF (light theme)   s t  PDF, choose theme
;;
;; Setup (init.el):
;;   (load "~/Dokumente/org2slides/org2slides.el")
;;   (with-eval-after-load 'org
;;     (define-key org-mode-map (kbd "C-c b") #'org2slides-export))

(defconst org2slides--dir
  (file-name-directory (or load-file-name buffer-file-name default-directory))
  "Directory this file was loaded from (the org2slides repository).")

(defgroup org2slides nil
  "Export reveal.js org decks to HTML + Beamer PDF via org2slides."
  :group 'org-export)

(defcustom org2slides-script (expand-file-name "org2slides" org2slides--dir)
  "Path to the org2slides script."
  :type 'file)

(defcustom org2slides-extra-args nil
  "Extra arguments passed to org2slides on every export.
E.g. (\"--light\") or (\"--theme\" \"mytheme\")."
  :type '(repeat string))

(defcustom org2slides-open-output t
  "Non-nil opens the result after a successful export.
The PDF when one was built, otherwise the HTML in the browser."
  :type 'boolean)

;;;###autoload
(defun org2slides-export (&optional debug extra-args)
  "Export the reveal.js org deck in the current buffer with org2slides.
By default both the HTML presentation and the Beamer PDF are built.
With prefix argument DEBUG, pass --debug (keep the intermediate
<deck>_beamer.org/.tex files, full pdflatex output). EXTRA-ARGS is a
list of additional org2slides arguments (e.g. (\"--html\"))."
  (interactive "P")
  (let ((src (buffer-file-name)))
    (unless (and src (string-suffix-p ".org" src t))
      (user-error "Current buffer is not visiting an .org file"))
    (when (buffer-modified-p)
      (save-buffer))
    (let* ((default-directory (file-name-directory src))
           (args (append (when debug '("--debug")) org2slides-extra-args extra-args))
           (result (if (member "--html" args)
                       (concat (file-name-sans-extension src) ".html")
                     (concat (file-name-sans-extension src) "_beamer.pdf")))
           (command (mapconcat #'shell-quote-argument
                               `(,org2slides-script ,@args ,src)
                               " "))
           (buffer (compilation-start command nil
                                      (lambda (_mode) "*org2slides*"))))
      (when org2slides-open-output
        (with-current-buffer buffer
          (add-hook 'compilation-finish-functions
                    (lambda (_buf status)
                      (when (string-prefix-p "finished" status)
                        (if (string-suffix-p ".html" result)
                            (browse-url (concat "file://" result))
                          (org-open-file result))))
                    nil t))))))

;;;###autoload
(defun org2slides-export-pdf (&optional debug)
  "Export only the Beamer PDF (C-u DEBUG keeps intermediates)."
  (interactive "P")
  (org2slides-export debug '("--pdf")))

;;;###autoload
(defun org2slides-export-html ()
  "Export only the reveal.js HTML presentation."
  (interactive)
  (org2slides-export nil '("--html")))

(defun org2slides--pdf-theme ()
  "Export the PDF with an interactively chosen theme.
Offers the built-ins; type any other name for a custom theme shipped in
themes/<name>/ next to the deck (or in $ORG2SLIDES_THEMES)."
  (org2slides-export nil
                    (list "--pdf" "--theme"
                          (completing-read "Theme: " '("dark" "light")
                                           nil nil nil nil "dark"))))

;; Register in the `C-c C-e' export dispatcher under `s'. The backend is a
;; menu-only shim (derived from `latex', its transcoders are never used):
;; every action shells out to the org2slides script. The dispatcher's
;; async/subtree/visible/body toggles don't apply and are ignored.
(with-eval-after-load 'ox
  (require 'ox-latex)
  (org-export-define-derived-backend 'org2slides 'latex
    :menu-entry
    '(?s "Export with org2slides (reveal HTML + Beamer PDF)"
         ((?s "HTML + PDF"
              (lambda (_a _s _v _b) (org2slides-export)))
          (?h "HTML only"
              (lambda (_a _s _v _b) (org2slides-export-html)))
          (?p "PDF only"
              (lambda (_a _s _v _b) (org2slides-export-pdf)))
          (?d "PDF, keep intermediates (--debug)"
              (lambda (_a _s _v _b) (org2slides-export-pdf t)))
          (?l "PDF (light theme)"
              (lambda (_a _s _v _b) (org2slides-export nil '("--pdf" "--light"))))
          (?t "PDF (choose theme)"
              (lambda (_a _s _v _b) (org2slides--pdf-theme)))))))

(provide 'org2slides)
;;; org2slides.el ends here
