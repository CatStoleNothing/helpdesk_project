document.addEventListener('DOMContentLoaded', function() {
    // Toggle sidebar
    const sidebarCollapse = document.getElementById('sidebarCollapse');
    if (sidebarCollapse) {
        sidebarCollapse.addEventListener('click', function() {
            const sidebar = document.getElementById('sidebar');
            const content = document.getElementById('content');

            sidebar.classList.toggle('active');
            content.classList.toggle('active');
        });
    }

    // Auto-hide alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(function(alert) {
        setTimeout(function() {
            const closeButton = alert.querySelector('.btn-close');
            if (closeButton) {
                closeButton.click();
            }
        }, 5000);
    });

    // File input custom display
    const fileInputs = document.querySelectorAll('.custom-file-input');
    fileInputs.forEach(function(input) {
        input.addEventListener('change', function(e) {
            const fileName = e.target.files[0] ? e.target.files[0].name : 'Выберите файл';
            const nextSibling = e.target.nextElementSibling;
            nextSibling.innerText = fileName;
        });
    });

    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Filter form submit on change
    const filterSelects = document.querySelectorAll('.filter-select');
    filterSelects.forEach(function(select) {
        select.addEventListener('change', function() {
            const form = select.closest('form');
            if (form) {
                form.submit();
            }
        });
    });

    // AJAX for ticket filter
    const filterForm = document.getElementById('ticket-filter-form');
    if (filterForm) {
        filterForm.addEventListener('submit', function(e) {
            e.preventDefault();

            const formData = new FormData(filterForm);

            fetch('/tickets/fragment', {
                method: 'POST',
                body: formData
            })
            .then(response => response.text())
            .then(html => {
                document.getElementById('tickets-table-container').innerHTML = html;
            })
            .catch(error => {
                console.error('Error:', error);
            });
        });
    }

    // AJAX for chat messages
    const chatForm = document.getElementById('chat-form');
    if (chatForm) {
        chatForm.addEventListener('submit', function(e) {
            e.preventDefault();

            const formData = new FormData(chatForm);
            const messageInput = document.getElementById('message-input');
            const chatMessages = document.querySelector('.chat-messages');

            // Clear the input
            messageInput.value = '';

            fetch('/send_chat_message', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Create message element
                    const messageDiv = document.createElement('div');
                    messageDiv.className = 'message message-outgoing';
                    if (data.message.is_internal) {
                        messageDiv.classList.add('message-internal');
                    }

                    let messageContent = `<div class="message-content">${data.message.content}</div>`;

                    if (data.message.attachment && data.message.attachment.is_image) {
                        messageContent += `<img src="${data.message.attachment.file_path}" alt="${data.message.attachment.file_name}" class="chat-attachment-img">`;
                    }

                    messageContent += `<div class="message-meta">
                                        <span>${data.message.sender_name}</span>
                                        <span>${data.message.time}</span>
                                      </div>`;

                    messageDiv.innerHTML = messageContent;

                    // Append message
                    chatMessages.appendChild(messageDiv);

                    // Scroll to bottom
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                } else {
                    alert('Ошибка: ' + data.error);
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('Произошла ошибка при отправке сообщения.');
            });
        });
    }

    // Chat file upload preview
    const chatImageInput = document.getElementById('chat-image-input');
    if (chatImageInput) {
        chatImageInput.addEventListener('change', function(e) {
            const previewContainer = document.getElementById('image-preview');

            if (previewContainer) {
                // Clear previous preview
                previewContainer.innerHTML = '';

                if (e.target.files.length > 0) {
                    const file = e.target.files[0];

                    if (file.type.match('image.*')) {
                        const reader = new FileReader();

                        reader.onload = function(event) {
                            const imgElement = document.createElement('img');
                            imgElement.src = event.target.result;
                            imgElement.className = 'img-fluid rounded mt-2';
                            imgElement.style.maxHeight = '150px';

                            const removeBtn = document.createElement('button');
                            removeBtn.className = 'btn btn-sm btn-danger mt-2';
                            removeBtn.innerHTML = '<i class="fas fa-times"></i> Удалить';
                            removeBtn.addEventListener('click', function() {
                                previewContainer.innerHTML = '';
                                chatImageInput.value = '';
                            });

                            previewContainer.appendChild(imgElement);
                            previewContainer.appendChild(removeBtn);
                        };

                        reader.readAsDataURL(file);
                    }
                }
            }
        });
    }

    // Toggle internal/external chat
    const chatTypeToggle = document.querySelectorAll('.chat-type-toggle');
    if (chatTypeToggle.length > 0) {
        chatTypeToggle.forEach(function(button) {
            button.addEventListener('click', function(e) {
                e.preventDefault();

                const chatType = this.dataset.chatType;
                const chatContainers = document.querySelectorAll('.chat-container');
                const toggleButtons = document.querySelectorAll('.chat-type-toggle');

                // Toggle active class on buttons
                toggleButtons.forEach(btn => btn.classList.remove('active'));
                this.classList.add('active');

                // Show/hide appropriate chat
                chatContainers.forEach(function(container) {
                    if (container.dataset.chatType === chatType) {
                        container.style.display = 'flex';
                    } else {
                        container.style.display = 'none';
                    }
                });
            });
        });
    }

    // Initialize date pickers if any
    const datePickers = document.querySelectorAll('.datepicker');
    if (datePickers.length > 0) {
        datePickers.forEach(function(input) {
            input.addEventListener('focus', function() {
                this.type = 'date';
            });

            input.addEventListener('blur', function() {
                if (!this.value) {
                    this.type = 'text';
                }
            });
        });
    }

    // Expandable ticket description
    const expandButtons = document.querySelectorAll('.expand-description');
    if (expandButtons.length > 0) {
        expandButtons.forEach(function(button) {
            button.addEventListener('click', function() {
                const descriptionElement = this.closest('.ticket-item').querySelector('.ticket-description');
                const isExpanded = descriptionElement.classList.contains('expanded');

                if (isExpanded) {
                    descriptionElement.classList.remove('expanded');
                    this.textContent = 'Развернуть';
                } else {
                    descriptionElement.classList.add('expanded');
                    this.textContent = 'Свернуть';
                }
            });
        });
    }

    // Image modal for enlarging images
    document.body.addEventListener('click', function(e) {
        if (e.target && e.target.classList.contains('chat-attachment-img')) {
            const modal = new bootstrap.Modal(document.getElementById('imageModal'));
            const modalImg = document.getElementById('modalImage');
            modalImg.src = e.target.src;
            modal.show();
        }
    });
});
